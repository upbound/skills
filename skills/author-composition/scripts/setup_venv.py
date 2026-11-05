#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a project-local venv that resolves every Python import in an Upbound project.

Nothing about the normal loop needs this: `up test run` and `up project build` run your
function in a container with the project's own pins. This venv exists for two things —
the function unit tests (the fast tier) and your editor, which otherwise reports every
`from models.io...` and `from crossplane.function import ...` as unresolved on completely
correct code.

Three rules decide the whole design, all verified rather than assumed:

1. **Install from the project's own pins, never by package name.** `resource.update()`
   serializes differently across SDK releases (control-plane-project-charter's
   `languages/python.md`). A venv holding a different SDK than the container is not a proxy
   for the real run.

2. **Install the generated models LAST, and editable.** Every function and test
   `pyproject.toml` declares `crossplane-models @ file:./../../.up/python` as an ordinary
   dependency, so installing one of them copies the models into site-packages and silently
   replaces an editable install. Installed editable and last, pip writes a plain .pth
   pointing at .up/python, so `up project build` regenerating the models — new provider,
   new Kind, changed field — is picked up with no reinstall at all.

3. **Create the venv on an interpreter the project's own pins accept.** Every generated
   `pyproject.toml` — the models package included — declares
   `requires-python = ">=3.11,<3.14"`. `python3` on a current machine is often already
   3.14: the venv is then created happily and *every* install into it fails with
   `requires a different Python`, leaving an empty venv. That is the exact state in which
   VS Code reports every `models.*` import unresolved no matter which interpreter you
   select, so this script reads the constraint first and picks a matching interpreter.

Usage:
    python3 setup_venv.py [--project <root>] [--venv .venv] [--no-vscode] [--no-recreate]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def find_root(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        if (d / "upbound.yaml").is_file():
            return d
    return None


def layout_of(d: Path) -> str:
    """sdk | embedded | unknown.

    Any pyproject.toml means the SDK layout, for a function and a test alike. The SDK
    layout ships its own function/main.py, so only a main.py or fn.py at the directory
    root means embedded.
    """
    if (d / "pyproject.toml").is_file():
        return "sdk"
    if (d / "main.py").is_file() or (d / "fn.py").is_file():
        return "embedded"
    return "unknown"


SPECIFIER = re.compile(r"(>=|<=|==|!=|~=|>|<)\s*(\d+)\.(\d+)")


def requires_python(root: Path) -> list[tuple[str, int, int]]:
    """Every (op, major, minor) clause the project's own packages declare.

    `up` writes `requires-python` into the models package and into every function and
    test pyproject. Reading it beats hardcoding a range that a later `up` may move.
    """
    clauses: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    files = [root / ".up" / "python" / "pyproject.toml"]
    for kind in ("functions", "tests"):
        base = root / kind
        if base.is_dir():
            files += sorted(base.glob("*/pyproject.toml"))
    for f in files:
        if not f.is_file():
            continue
        for line in f.read_text().splitlines():
            m = re.match(r"""\s*requires-python\s*=\s*["'](.+?)["']""", line)
            if not m:
                continue
            if m.group(1) not in seen:
                seen.add(m.group(1))
                clauses += [(op, int(a), int(b)) for op, a, b in SPECIFIER.findall(m.group(1))]
            break
    return clauses


def satisfies(ver: tuple[int, int], clauses: list[tuple[str, int, int]]) -> bool:
    for op, major, minor in clauses:
        want = (major, minor)
        if op == ">=" and not ver >= want: return False
        if op == ">" and not ver > want: return False
        if op == "<=" and not ver <= want: return False
        if op == "<" and not ver < want: return False
        if op == "==" and ver != want: return False
        if op == "!=" and ver == want: return False
        if op == "~=" and not (ver >= want and ver[0] == major): return False
    return True


def describe(clauses: list[tuple[str, int, int]]) -> str:
    return ", ".join(f"{op}{a}.{b}" for op, a, b in clauses) or "any version"


def interpreter_version(py: Path) -> tuple[int, int] | None:
    rc, out = run([str(py), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"])
    if rc != 0:
        return None
    try:
        major, minor = out.strip().splitlines()[-1].split(".")[:2]
        return (int(major), int(minor))
    except (ValueError, IndexError):
        return None


def pick_interpreter(clauses: list[tuple[str, int, int]]) -> tuple[Path, tuple[int, int]] | None:
    """The interpreter running this script if the project accepts it, else the newest
    `python3.N` on PATH that it does. Newest-first matters: with `<3.14` in force, 3.13
    is the one to want, and falling back to 3.11 would pin the venv to an old runtime
    for no reason."""
    if satisfies(sys.version_info[:2], clauses):
        return Path(sys.executable), sys.version_info[:2]
    for minor in range(30, 5, -1):
        if satisfies((3, minor), clauses):
            found = shutil.which(f"python3.{minor}")
            if found:
                return Path(found), (3, minor)
    return None


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="path inside the project (default: cwd)")
    ap.add_argument("--venv", default=".venv",
                    help="venv path, relative to the project root (default: .venv, which "
                         "VS Code discovers on its own)")
    ap.add_argument("--no-vscode", action="store_true",
                    help="skip writing .vscode/settings.json")
    ap.add_argument("--no-recreate", action="store_true",
                    help="never delete an existing venv; report and stop instead if it "
                         "is bound to an interpreter this project rejects")
    args = ap.parse_args()

    root = find_root(Path(args.project).resolve())
    if root is None:
        print(f"ERROR: no upbound.yaml in {args.project} or any parent.", file=sys.stderr)
        return 2

    models_pkg = root / ".up" / "python"
    if not (models_pkg / "models").is_dir():
        print("ERROR: no .up/python/models. The models are generated, never hand-written:\n"
              "    up project build", file=sys.stderr)
        return 2

    venv = (root / args.venv).resolve()
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    clauses = requires_python(root)
    print(f"project: {root}")
    print(f"python:  {describe(clauses)}  (from the project's own pyproject.toml files)")

    if py.is_file():
        have = interpreter_version(py)
        if have is None:
            print(f"venv:    {venv.relative_to(root)} exists but its interpreter does not "
                  f"run — replacing it", flush=True)
            if args.no_recreate:
                print(f"ERROR: delete it and re-run:\n    rm -rf {venv}", file=sys.stderr)
                return 1
            shutil.rmtree(venv)
        elif not satisfies(have, clauses):
            # A venv is bound for life to the interpreter that created it; selecting a
            # different one in VS Code does not re-point it. Left in place, every install
            # below fails with "requires a different Python" and the venv stays empty —
            # and an empty .venv at the project root is worse than none, because VS Code
            # discovers it and then reports every models.* import unresolved.
            print(f"venv:    {venv.relative_to(root)} is Python {have[0]}.{have[1]}, which "
                  f"this project rejects ({describe(clauses)})", flush=True)
            if args.no_recreate:
                print(f"ERROR: a venv cannot be re-pointed at another interpreter. Delete "
                      f"it and re-run:\n    rm -rf {venv}", file=sys.stderr)
                return 1
            print("         replacing it — a venv cannot be re-pointed at another "
                  "interpreter")
            shutil.rmtree(venv)
        else:
            print(f"venv:    {venv.relative_to(root)} (Python {have[0]}.{have[1]}, "
                  f"exists — reusing)")

    if not py.is_file():
        picked = pick_interpreter(clauses)
        if picked is None:
            print(f"ERROR: this project needs Python {describe(clauses)} and no matching "
                  f"interpreter is on PATH.\n"
                  f"    This one is {sys.version_info[0]}.{sys.version_info[1]}, and no "
                  f"python3.N in range was found.\n"
                  f"    macOS:  brew install python@3.13\n"
                  f"    Then re-run this script.", file=sys.stderr)
            return 2
        interp, iv = picked
        print(f"creating venv: {venv.relative_to(root)}  "
              f"(Python {iv[0]}.{iv[1]} — {interp})")
        rc, out = run([str(interp), "-m", "venv", str(venv)])
        if rc != 0:
            print(out, file=sys.stderr)
            return 1

    pip = [str(py), "-m", "pip", "install", "-q"]
    run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])

    # 1. Function and test packages, from their own pins.
    installed, failures = [], []
    for kind in ("functions", "tests"):
        base = root / kind
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            lay = layout_of(d)
            rel = d.relative_to(root)
            if lay == "sdk" and (d / "pyproject.toml").is_file():
                # cwd=d is load-bearing: pip resolves the pyproject's relative
                # `crossplane-models @ file:./../../.up/python` against the working
                # directory, not against the pyproject's own directory.
                rc, out = run([*pip, "-e", "."], cwd=d)
            elif lay == "embedded" and (d / "requirements.txt").is_file():
                rc, out = run([*pip, "-r", str(d / "requirements.txt")])
            else:
                print(f"  skip     {rel} (layout={lay}, nothing to install)")
                continue
            (installed if rc == 0 else failures).append((rel, lay, out))
            print(f"  {'ok  ' if rc == 0 else 'FAIL'}     {rel}  ({lay})")

    # 2. Models LAST and editable, so regenerating them needs no reinstall. This has to
    #    come after the packages above, each of which would otherwise copy the models in.
    rc, out = run([*pip, "-e", str(models_pkg)])
    if rc != 0:
        sys.stdout.flush()
        print("FAIL     .up/python (models)", file=sys.stderr)
        print(out, file=sys.stderr)
        return 1
    print("  ok       .up/python  (models, editable — regeneration needs no reinstall)")

    # 3. Verify rather than assume.
    probe = ("import importlib.util as u, sys;"
             "sys.exit(0 if u.find_spec('models') and u.find_spec('crossplane.function') "
             "else 1)")
    rc, _ = run([str(py), "-c", probe])
    if rc != 0:
        print("ERROR: venv built but `models` or `crossplane.function` still does not "
              "import. Check the failures above.", file=sys.stderr)
        return 1

    editable = run([str(py), "-m", "pip", "list", "--editable", "--format=json"])[1]
    try:
        eds = {p["name"] for p in json.loads(editable)}
    except Exception:
        eds = set()
    if "crossplane-models" not in eds:
        print("WARNING: crossplane-models is installed but NOT editable — regenerated "
              "models will not be picked up. Re-run this script.", file=sys.stderr)

    # 4. VS Code: the interpreter is all it needs. Verified with pyright against both
    #    layouts — zero unresolved imports, no extraPaths required.
    if not args.no_vscode:
        vs = root / ".vscode"
        vs.mkdir(exist_ok=True)
        settings_path = vs / "settings.json"
        settings = {}
        if settings_path.is_file():
            try:
                settings = json.loads(settings_path.read_text() or "{}")
            except json.JSONDecodeError:
                print(f"NOTE: {settings_path.relative_to(root)} is not valid JSON "
                      f"(comments are allowed in VS Code but not here) — leaving it alone. "
                      f"Set the interpreter manually.", file=sys.stderr)
                settings = None
        if settings is not None:
            interp = f"${{workspaceFolder}}/{venv.relative_to(root)}/bin/python"
            settings["python.defaultInterpreterPath"] = interp
            # The SDK scaffold subclasses grpcv1.FunctionRunnerService, whose RunFunction
            # is a ten-argument @staticmethod client stub, so Pylance flags an override
            # mismatch on every generated function. Registration is duck-typed
            # (add_FunctionRunnerServiceServicer_to_server only reads .RunFunction), and
            # the SDK's own runtime.py annotates the same base, so the scaffold is right
            # and the diagnostic is noise. Switch off the one rule rather than let it
            # invite a restructure of correct code.
            overrides = settings.setdefault("python.analysis.diagnosticSeverityOverrides", {})
            if isinstance(overrides, dict):
                overrides.setdefault("reportIncompatibleMethodOverride", "none")
            settings_path.write_text(json.dumps(settings, indent=2) + "\n")
            print(f"wrote    {settings_path.relative_to(root)}  "
                  f"(python.defaultInterpreterPath)")

    print()
    print(f"Select this interpreter in VS Code (Python: Select Interpreter):")
    print(f"    {py}")
    print()
    print("Re-run this script after adding a function or test directory. You do NOT need to "
          "re-run it after `up project build` regenerates models — that is what the editable "
          "install buys you.")
    if failures:
        sys.stdout.flush()
        print(f"\n{len(failures)} package(s) failed to install:", file=sys.stderr)
        for rel, lay, out in failures:
            print(f"--- {rel} ({lay}) ---\n{out.strip()[-800:]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
