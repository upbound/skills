#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Print the facts a Python composition author needs, so nothing has to be guessed.

Usage:
    python3 probe_project.py                                   # project facts only
    python3 probe_project.py Bucket StorageBucket              # + resolve these Kinds
    python3 probe_project.py --project ~/src/my-proj Bucket    # from anywhere

Without --project, the project root is found by walking up from the current directory
looking for upbound.yaml.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def find_root(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        if (d / "upbound.yaml").is_file():
            return d
    return None


def layout_of(d: Path) -> str:
    """Which of the two Python layouts a function/test directory uses."""
    if (d / "pyproject.toml").is_file():
        return "sdk"
    if (d / "main.py").is_file():
        return "embedded"
    return "unknown"


def import_prefix(layout: str) -> str:
    return "models." if layout == "sdk" else ".model."


def kind_index(models: Path) -> dict[str, list[tuple[str, str]]]:
    """Map lowercased Kind -> [(dotted module path, version), ...] from the model tree."""
    index: dict[str, list[tuple[str, str]]] = {}
    for version_file in models.rglob("v*.py"):
        if version_file.name == "__init__.py":
            continue
        version = version_file.stem
        if not re.fullmatch(r"v\d+(alpha\d+|beta\d+)?", version):
            continue
        pkg = version_file.parent
        dotted = ".".join(pkg.relative_to(models).parts)
        if not dotted:
            continue
        index.setdefault(pkg.name, []).append((dotted, version))
    return index


def classes_in(version_file: Path) -> list[str]:
    try:
        text = version_file.read_text()
    except OSError:
        return []
    return re.findall(r"^class (\w+)\(BaseModel\):", text, re.M)


FIELD_RE = re.compile(r"^\s{4}(\w+)\s*:\s*(.+?)(?:\s*=\s*.*)?$")


def class_fields(version_file: Path) -> dict[str, list[tuple[str, str]]]:
    """Map each class in the module to its [(field, type)] list."""
    if not version_file.is_file():
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    current = None
    for line in version_file.read_text().splitlines():
        m = re.match(r"^class (\w+)\(BaseModel\):", line)
        if m:
            current = m.group(1)
            out[current] = []
            continue
        if current:
            f = FIELD_RE.match(line)
            if f and not line.lstrip().startswith(('"""', "#")):
                out[current].append((f.group(1), f.group(2).strip()))
    return out


def print_fields(version_file: Path, kind: str) -> None:
    classes = class_fields(version_file)
    fp = classes.get("ForProvider")
    if fp is None:
        # An XR has no ForProvider — its authored surface is Spec. Show that instead of
        # reporting nothing, which reads as "this Kind has no fields".
        spec = classes.get("Spec")
        if spec is None:
            print(f"      (no ForProvider and no Spec class in {version_file.name} — "
                  f"read the file directly)")
            return
        print(f"      no ForProvider (this is an XR, not a managed resource)")
        print(f"      Spec fields ({len(spec)}):")
        for name, typ in spec:
            print(f"        {name}: {typ}")
        return
    print(f"      ForProvider fields ({len(fp)}):")
    for name, typ in fp:
        print(f"        {name}: {typ}")

    # Cross-resource references, anywhere in the module (they are often nested).
    # Spec-level refs are not cross-resource references to author: providerConfigRef is
    # API-server-defaulted (setting it is a defect), and connection-secret refs are
    # unrelated. matchControllerRef is a selector's own knob, not a field you set.
    SKIP_CLASSES = {"Spec", "ProviderConfigRef", "WriteConnectionSecretToRef",
                    "PublishConnectionDetailsTo", "ProviderConfigRefPolicy"}
    SKIP_FIELDS = {"matchControllerRef"}
    refs = [(cls, name, typ)
            for cls, fields in classes.items()
            for name, typ in fields
            if name.endswith(("Ref", "Refs", "Selector"))
            and cls not in SKIP_CLASSES and name not in SKIP_FIELDS]
    if refs:
        print()
        print("      CROSS-RESOURCE REFERENCES — prefer these over plumbing an ID/ARN yourself.")
        print("      Setting a *Ref lets the PROVIDER resolve the value, which keeps the")
        print("      composition single-pass: you never read the other resource's status.")
        for cls, name, typ in refs:
            where = "ForProvider" if cls == "ForProvider" else f"ForProvider...{cls}"
            print(f"        {where}.{name}: {typ}")
    else:
        print()
        print("      (no *Ref/*Selector fields — this Kind has no cross-resource references)")

    lists = [n for n, t in fp if t.startswith("Optional[List[")]
    if lists:
        print()
        print("      NOTE: Upjet keeps Terraform's SINGULAR names for repeatable blocks —")
        print(f"      these are lists despite the singular name: {', '.join(lists)}")



def project_xr_kinds(root: Path) -> dict[str, Path]:
    """Kinds this project defines itself, from its XRDs.

    A Kind declared in apis/**/definition.yaml belongs to this project, not to a
    dependency. Telling the user to `up dep add` a package for their own XR sends them
    hunting the marketplace for something that cannot exist; the actual remedy is to
    build the project so its models are generated.
    """
    found: dict[str, Path] = {}
    apis = root / "apis"
    if not apis.is_dir():
        return found
    for defn in apis.rglob("*.yaml"):
        try:
            text = defn.read_text(errors="ignore")
        except OSError:
            continue
        if "CompositeResourceDefinition" not in text:
            continue
        for line in text.splitlines():
            s = line.strip()
            for key in ("kind:", "listKind:"):
                if s.startswith(key):
                    v = s[len(key):].strip().strip('"\'')
                    if v and v != "CompositeResourceDefinition":
                        found.setdefault(v.lower(), defn)
    return found


def crossplane_generation(root: Path) -> str:
    """"v2", "v1", or "unknown" — read from the project's own XRDs.

    This governs more of the guidance than the language does: a v1 project uses the
    non-namespaced provider models and a cluster-scoped ProviderConfig, and pointing it
    at the .m. models breaks it. A template does not tell you which one a project is:
    the CLI's cloud templates (aws-s3, azure-storage, gcp-storage) ship v1 XRDs and
    k8s-webapp a v2 one, so the XRDs' own apiVersion is the only thing read here.
    """
    seen = set()
    apis = root / "apis"
    if not apis.is_dir():
        return "unknown"
    for f in sorted(apis.rglob("*.yaml")):
        try:
            text = f.read_text()
        except OSError:
            continue
        if "kind: CompositeResourceDefinition" not in text:
            continue
        if "apiextensions.crossplane.io/v2" in text:
            seen.add("v2")
        elif "apiextensions.crossplane.io/v1" in text:
            seen.add("v1")
    if len(seen) == 1:
        return seen.pop()
    if seen:
        return "mixed"
    return "unknown"


def version_key(version: str) -> tuple[int, int, int]:
    """Sort key giving Kubernetes API-version precedence, newest first.

    v1 > v2beta1 is wrong; the real order is by major, then stability (ga > beta > alpha),
    then the stability revision. Returned negated so plain ascending sort puts newest first.
    """
    m = re.fullmatch(r"v(\d+)(?:(alpha|beta)(\d+))?", version)
    if not m:
        return (0, 0, 0)
    major = int(m.group(1))
    stage = {None: 2, "beta": 1, "alpha": 0}[m.group(2)]
    rev = int(m.group(3) or 0)
    return (-major, -stage, -rev)


def model_group(dotted: str) -> str:
    """The API group a model belongs to: its module path minus the Kind, `.m.` removed.

    io.upbound.m.aws.s3.bucket -> io.upbound.aws.s3
    io.upbound.aws.s3.bucket   -> io.upbound.aws.s3   (same group, different generation)
    io.upbound.m.gcp.storage.bucket -> io.upbound.gcp.storage   (genuinely different)
    """
    parts = [seg for seg in dotted.split(".")[:-1] if seg != "m"]
    return ".".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kinds", nargs="*", help="Resource Kinds to resolve, e.g. Bucket StorageBucket")
    ap.add_argument("--fields", action="store_true",
                    help="also print ForProvider fields and cross-resource *Ref/*Selector fields")
    ap.add_argument("--project", metavar="PATH",
                    help="Project root (or any directory inside it). Defaults to the current directory.")
    args = ap.parse_args()

    start = Path(args.project).expanduser().resolve() if args.project else Path.cwd().resolve()
    if args.project and not start.is_dir():
        print(f"ERROR: --project path is not a directory: {start}", file=sys.stderr)
        return 10  # validation failure
    root = find_root(start)
    if root is None:
        print(f"ERROR: no upbound.yaml found in {start} or any parent. "
              f"Pass --project <project-root>.", file=sys.stderr)
        return 2  # not found
    os.chdir(root)
    print(f"project root: {root}")

    generation = crossplane_generation(root)
    print(f"crossplane:    {generation}" + {
        "v1": "  <- non-namespaced provider models; the .m. groups do NOT apply here",
        "v2": "  <- namespaced (.m.) provider models",
        "mixed": "  <- some XRDs are v1 and some v2; check each one",
        "unknown": "  <- no XRD found under apis/",
    }[generation])

    models = root / ".up" / "python" / "models"
    models_missing = not models.is_dir()
    print("models:        " + (
        "MISSING .up/python/models -> run `up project build` (.up/ is gitignored "
        "and starts empty on a fresh checkout; the build fetches the dependencies "
        "itself; models are generated, never hand-written)"
        if models_missing else str(models.relative_to(root))))

    for kind_dir, label in (("functions", "function"), ("tests", "test")):
        base = root / kind_dir
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            lay = layout_of(d)
            print(f"{label:<9} {d.relative_to(root)}  layout={lay}  import prefix={import_prefix(lay)!r}")

    # The is_dir() guard must sit before the iterdir() it protects: in a comprehension
    # the inner iterable is evaluated eagerly, so a trailing `if` does not prevent the
    # call. A project with no tests/ directory used to crash here with FileNotFoundError.
    layouts = {layout_of(d)
               for base in ("functions", "tests")
               if (root / base).is_dir()
               for d in (root / base).iterdir()
               if d.is_dir()}
    layouts.discard("unknown")
    prefix = import_prefix(layouts.pop()) if len(layouts) == 1 else "<prefix>"
    if prefix == "<prefix>":
        print("NOTE: mixed or unknown layouts — use each directory's own prefix, listed above.")

    if models_missing:
        # The layout and import prefix above need no models, so they are printed even on a
        # fresh checkout. Kind resolution genuinely cannot proceed.
        return 2  # not found

    if not args.kinds:
        print("\nPass Kinds to resolve their import paths, e.g.:  python3 probe_project.py Bucket StorageBucket")
        return 0

    index = kind_index(models)
    own_kinds = project_xr_kinds(root)
    print()
    exit_code = 0
    for kind in args.kinds:
        matches = index.get(kind.lower(), [])
        if not matches:
            own = project_xr_kinds(root)
            src = own.get(kind.lower())
            if src is not None:
                rel = src.relative_to(root) if src.is_relative_to(root) else src
                print(f"{kind}: defined by THIS project ({rel}), not by a dependency. "
                      f"Its model is generated by `up project build` — run that. "
                      f"Do not `up dep add` anything; there is no package to add.")
            else:
                print(f"{kind}: NOT FOUND in the model tree, and no XRD in apis/ defines "
                      f"it. If it belongs to a provider, add it (`up dep add <xpkg ref>` "
                      f"then `up project build`). If it is meant to be this project's "
                      f"own XR, its XRD is missing.")
            exit_code = 2  # requested Kind not found
            continue
        # Namespaced (.m.) models first, then newest version first.
        def rank(m: tuple[str, str]) -> tuple[int, tuple[int, int, int]]:
            dotted, version = m
            namespaced = ".m." in f".{dotted}." or not dotted.startswith("io.upbound")
            # A v1 project wants the non-namespaced models; ranking .m. first there would
            # recommend an import that breaks it.
            wanted = (not namespaced) if generation == "v1" else namespaced
            # Newest API version first. Plain string order puts v1beta1 above v1beta2 and
            # would label the older module "USE THIS".
            return (0 if wanted else 1, version_key(version))

        # Same Kind can exist in unrelated API groups: a project XR and a provider MR, or
        # two providers (aws s3 Bucket vs gcp storage Bucket). Compare the group — the module
        # path without its trailing Kind segment — with `.m.` normalised away, so the v1 and
        # v2 models of the SAME Kind do not read as two different groups.
        groups = {model_group(d) for d, _ in matches}
        ambiguous = len(groups) > 1
        print(f"{kind}:" + ("   AMBIGUOUS - more than one API group defines this Kind, pick by group"
                            if ambiguous else ""))
        for i, (dotted, version) in enumerate(sorted(matches, key=rank, reverse=False)):
            # A project's own XR reverses into io.upbound.* too when its group ends in
            # upbound.io, and an XRD legitimately serves v1 — only flag provider models.
            is_own_xr = kind.lower() in own_kinds
            non_namespaced = (not is_own_xr
                              and dotted.startswith("io.upbound")
                              and ".m." not in f".{dotted}.")
            if non_namespaced and generation == "v1":
                tag = ("  <- USE THIS (this project is Crossplane v1)" if i == 0
                       else "")
            elif non_namespaced and generation == "mixed":
                tag = "  <- non-namespaced: for this project's v1 XRDs only"
            elif non_namespaced:
                tag = "  <- non-namespaced provider model, do NOT use in v2"
            elif generation == "mixed":
                tag = "  <- namespaced: for this project's v2 XRDs" if i == 0 else ""
            elif generation == "v1" and not is_own_xr:
                tag = "  <- namespaced model; only after migrating this project to v2"
            elif is_own_xr and i == 0:
                tag = "  <- USE THIS (this project's own XR; its version comes from the XRD)"
            elif i == 0 and not ambiguous:
                tag = "  <- USE THIS"
            else:
                tag = ""
            print(f"    from {prefix}{dotted} import {version}{tag}")
            if i == 0:
                nested = classes_in(models / Path(*dotted.split(".")) / f"{version}.py")
                version_file = models / Path(*dotted.split(".")) / f"{version}.py"
                if nested:
                    shown = ", ".join(nested[:18])
                    more = f", ... (+{len(nested) - 18} more)" if len(nested) > 18 else ""
                    print(f"      classes (module-qualified, UNPREFIXED): {shown}{more}")
                if args.fields:
                    print_fields(version_file, kind)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
