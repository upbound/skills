#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Structural validation for this repository.

Standard library only, so CI needs nothing but python3 and `make check` runs
exactly what CI runs.

Usage:
    python3 hack/validate.py all
    python3 hack/validate.py frontmatter | links | scripts | manifests | readme | hygiene
    python3 hack/validate.py readme --fix
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter import FrontmatterError, parse  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
PLUGIN_MANIFEST = REPO / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO / ".claude-plugin" / "marketplace.json"
README = REPO / "README.md"

REQUIRED_KEYS = {"name", "description"}
ALLOWED_KEYS = REQUIRED_KEYS | {"license", "references"}
BANNED_KEYS = {
    "allowed-tools": "Claude Code honors it, Codex and Cursor ignore it, so the "
                     "skill behaves differently per agent without saying so",
    "model": "pins the skill to one vendor's model names",
    "context": "Claude Code specific",
    "agent": "Claude Code specific",
    "user-invocable": "Claude Code specific",
    "metadata": "nested mappings are not portable",
    "version": "the plugin has one version, in .claude-plugin/plugin.json",
}

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX = 64
DESC_MIN, DESC_MAX = 40, 1024
SKILL_MAX_LINES = 500

BEGIN_MARKER = "<!-- BEGIN skills-table -->"
END_MARKER = "<!-- END skills-table -->"

# Markdown links, allowing an optional title so `[x](y.md "Title")` does not
# report y.md "Title" as a missing file.
LINK_RE = re.compile(
    r"""\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*"|\s+'[^']*'|\s+\([^)]*\))?\s*\)"""
)
BACKTICK_PATH_RE = re.compile(r"`((?:references|scripts)/[^`\s]+)`")
FENCE_RE = re.compile(r"^(```+|~~~+).*?^\1", re.MULTILINE | re.DOTALL)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".gz", ".zip"}


class Finding(NamedTuple):
    path: Path
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f"{rel(self.path)}:{self.line}" if self.line else rel(self.path)
        return f"{where}: {self.message}"

    def annotation(self) -> str:
        loc = f",line={self.line}" if self.line else ""
        return f"::error file={rel(self.path)}{loc}::{self.message}"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def inside(child: Path, parent: Path) -> bool:
    """Resolved on both sides: a symlinked checkout otherwise reports false escapes."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def read(path: Path) -> str:
    """utf-8-sig so a BOM does not masquerade as a missing frontmatter fence."""
    return path.read_text(encoding="utf-8-sig")


def skill_dirs() -> list[Path]:
    if not SKILLS.is_dir():
        return []
    return sorted(p for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("."))


def prose(text: str) -> str:
    """Drop fenced blocks so documentation examples are not link-checked."""
    return FENCE_RE.sub("", text)


def git_lines(*args: str) -> list[str] | None:
    """git output split on NUL, or None when git could not run at all.

    None is distinct from an empty list so a caller can tell "no files" from
    "could not look", and report the second rather than passing.

    -z because without it core.quotePath mangles non-ASCII names into escapes.
    """
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [line for line in out.decode("utf-8", "surrogateescape").split("\0") if line]


@functools.lru_cache(maxsize=1)
def detect_license() -> str | None:
    path = REPO / "LICENSE"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if "Apache License" in text and "Version 2.0" in text:
        return "Apache-2.0"
    if "MIT License" in text or "Permission is hereby granted, free of charge" in text:
        return "MIT"
    return None


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def check_frontmatter() -> Iterator[Finding]:
    """Frontmatter parses, and stays inside the portable subset."""
    for skill in skill_dirs():
        md = skill / "SKILL.md"
        if not md.is_file():
            yield Finding(skill, "no SKILL.md")
            continue
        try:
            text = read(md)
            meta, body = parse(text)
        except FrontmatterError as exc:
            yield Finding(md, str(exc))
            continue
        except OSError as exc:
            yield Finding(md, f"cannot be read: {exc}")
            continue

        for key in sorted(set(meta) - ALLOWED_KEYS):
            why = BANNED_KEYS.get(key)
            yield Finding(md, f"frontmatter key {key!r} is not permitted"
                              f"{f' ({why})' if why else ''}. See CONTRIBUTING.md")
        for key in sorted(REQUIRED_KEYS - set(meta)):
            yield Finding(md, f"frontmatter is missing required key {key!r}")

        yield from _check_name(md, skill, meta.get("name"))
        yield from _check_description(md, meta.get("description"))

        license_id = meta.get("license")
        repo_license = detect_license()
        if isinstance(license_id, str) and repo_license and license_id != repo_license:
            yield Finding(md, f"license {license_id!r} does not match the repository "
                              f"license {repo_license!r}")

        stripped = body.lstrip("\n")
        if stripped and not stripped.startswith("# "):
            yield Finding(md, "first line after the frontmatter must be an H1")

        lines = len(text.splitlines())
        if lines > SKILL_MAX_LINES:
            yield Finding(md, f"{lines} lines, maximum {SKILL_MAX_LINES}. "
                              f"Move detail into references/")


def _check_name(md: Path, skill: Path, name: object) -> Iterator[Finding]:
    if name is None:
        return
    if not isinstance(name, str) or not name:
        yield Finding(md, "name must be a non-empty string")
        return
    if not NAME_RE.match(name):
        yield Finding(md, f"name {name!r} must be lowercase kebab-case")
    if len(name) > NAME_MAX:
        yield Finding(md, f"name is {len(name)} characters, maximum {NAME_MAX}")
    if name != skill.name:
        yield Finding(md, f"name {name!r} does not match directory {skill.name!r}; "
                          f"they must be identical")


def _check_description(md: Path, desc: object) -> Iterator[Finding]:
    if desc is None:
        return
    if not isinstance(desc, str) or not desc:
        yield Finding(md, "description must be a non-empty string")
        return
    if len(desc) < DESC_MIN:
        yield Finding(md, f"description is {len(desc)} characters, minimum {DESC_MIN}")
    if len(desc) > DESC_MAX:
        yield Finding(md, f"description is {len(desc)} characters, maximum {DESC_MAX}")
    if desc.lower().startswith("proactively"):
        yield Finding(md, "description opens with 'PROACTIVELY', spending its most "
                          "valuable words on an instruction. Lead with what it does")


def check_links() -> Iterator[Finding]:
    """Every referenced path resolves, and stays inside its own skill."""
    for skill in skill_dirs():
        md = skill / "SKILL.md"
        declared: set[str] = set()
        if md.is_file():
            try:
                meta, _ = parse(read(md))
                refs = meta.get("references")
                declared = {r for r in refs if isinstance(r, str)} if isinstance(refs, list) else set()
            except (FrontmatterError, OSError):
                pass  # reported by check_frontmatter

        linked: set[str] = set()
        for doc in sorted(skill.rglob("*.md")):
            try:
                text = prose(read(doc))
            except OSError as exc:
                yield Finding(doc, f"cannot be read: {exc}")
                continue

            # Markdown links resolve from the document, as markdown says. A
            # backticked bare path in prose means the skill root, which is how a
            # reader takes it.
            targets = [(t, doc.parent) for t in set(LINK_RE.findall(text))]
            targets += [(t, skill) for t in set(BACKTICK_PATH_RE.findall(text))]

            for target, base in sorted(targets):
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                clean = target.split("#", 1)[0].split("?", 1)[0].strip()
                if not clean:
                    continue
                if clean.startswith(("/", "~")):
                    yield Finding(doc, f"{clean!r} is an absolute path; use one relative "
                                       f"to the file")
                    continue

                resolved = (base / clean).resolve()
                if not inside(resolved, REPO):
                    yield Finding(doc, f"{clean!r} resolves outside the repository. A "
                                       f"plugin must not reach outside its own directory")
                elif not inside(resolved, skill):
                    yield Finding(doc, f"{clean!r} resolves outside {rel(skill)}. Skills "
                                       f"must be self-contained")
                elif not resolved.exists():
                    yield Finding(doc, f"{clean!r} does not exist")
                elif doc == md and inside(resolved, skill / "references"):
                    linked.add(resolved.relative_to(skill.resolve()).as_posix())

        yield from _check_references_dir(skill, md, linked, declared)


def _check_references_dir(skill: Path, md: Path, linked: set[str],
                          declared: set[str]) -> Iterator[Finding]:
    refs_dir = skill / "references"
    if not refs_dir.is_dir():
        if declared:
            yield Finding(md, f"references is set but {rel(refs_dir)} does not exist")
        return
    on_disk = {p.relative_to(skill).as_posix() for p in refs_dir.rglob("*.md")}
    for orphan in sorted(on_disk - linked - declared):
        yield Finding(skill, f"{orphan} exists but SKILL.md never links it. "
                             f"An unlinked reference is never read")
    for missing in sorted(declared - on_disk):
        yield Finding(md, f"references lists {missing!r}, which does not exist")


def check_scripts() -> Iterator[Finding]:
    """Scripts are executable, have a shebang, and are documented."""
    modes = {}
    for entry in git_lines("ls-files", "-s", "-z", "--", "skills") or []:
        meta, _, path = entry.partition("\t")
        modes[path] = meta.split()[0]

    # A skill may download something into its own scripts/ at runtime and gitignore
    # it -- upbound-hub does exactly that with the credential helper. Without this,
    # merely using a skill makes `make check` fail in that checkout, on three counts
    # at once: untracked, no shebang, undocumented. Anything git is deliberately
    # ignoring is not ours to check.
    ignored = set(git_lines("ls-files", "--others", "--ignored",
                            "--exclude-standard", "-z", "--", "skills") or [])

    for skill in skill_dirs():
        scripts_dir = skill / "scripts"
        if not scripts_dir.is_dir():
            continue

        mentioned: set[str] = set()
        for doc in skill.rglob("*.md"):
            try:
                text = read(doc)
            except OSError:
                continue
            for target in set(LINK_RE.findall(text)) | set(BACKTICK_PATH_RE.findall(text)):
                mentioned.add(Path(target.split("#", 1)[0]).name)
            mentioned.update(re.findall(r"[\w./-]*scripts/([\w.-]+)", text))

        for script in sorted(p for p in scripts_dir.iterdir() if p.is_file()):
            if script.name.startswith("."):
                continue
            key = rel(script)
            if key in ignored:
                continue

            with script.open("rb") as handle:
                if handle.read(2) != b"#!":
                    yield Finding(script, "no shebang on line 1")

            mode = modes.get(key)
            if mode is None:
                yield Finding(script, "not tracked by git, so its mode cannot be checked")
            elif not mode.endswith("755"):
                yield Finding(script, f"git mode is {mode}, expected 100755. "
                                      f"Run: git update-index --chmod=+x {key}")

            if script.name not in mentioned:
                yield Finding(script, f"no .md in {rel(skill)} mentions it. "
                                      f"Remove it or document it")


def check_manifests() -> Iterator[Finding]:
    """Manifests parse, agree with each other, and agree with LICENSE."""
    plugin = _load_json(PLUGIN_MANIFEST)
    if isinstance(plugin, Finding):
        yield plugin
        return
    market = _load_json(MARKETPLACE_MANIFEST)
    if isinstance(market, Finding):
        yield market
        return

    if not plugin.get("name"):
        yield Finding(PLUGIN_MANIFEST, "name is required")

    version = plugin.get("version")
    if version is None:
        yield Finding(PLUGIN_MANIFEST, "version is required. Without it every commit "
                                       "ships to users as a new version")
    elif not (isinstance(version, str) and SEMVER_RE.match(version)):
        yield Finding(PLUGIN_MANIFEST, f"version {version!r} is not semver")

    repo_license = detect_license()
    declared = plugin.get("license")
    if repo_license and declared and declared != repo_license:
        yield Finding(PLUGIN_MANIFEST, f"license {declared!r} does not match LICENSE, "
                                       f"which is {repo_license!r}")

    entries = market.get("plugins")
    if not isinstance(entries, list) or not entries:
        yield Finding(MARKETPLACE_MANIFEST, "plugins must be a non-empty list")
        return

    for index, entry in enumerate(entries):
        yield from _check_marketplace_entry(index, entry, plugin)


def _check_marketplace_entry(index: int, entry: object, plugin: dict) -> Iterator[Finding]:
    where = f"plugins[{index}]"
    if not isinstance(entry, dict):
        yield Finding(MARKETPLACE_MANIFEST, f"{where} must be an object")
        return

    source = entry.get("source")
    if not isinstance(source, str):
        return  # non-local sources are out of scope here

    target = (REPO / source).resolve()
    if not inside(target, REPO):
        yield Finding(MARKETPLACE_MANIFEST, f"{where}: source {source!r} resolves outside "
                                            f"the repository")
        return
    if not target.is_dir():
        yield Finding(MARKETPLACE_MANIFEST, f"{where}: source {source!r} is not a directory")
        return

    manifest = target / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        yield Finding(MARKETPLACE_MANIFEST, f"{where}: {source!r} has no "
                                            f".claude-plugin/plugin.json")
        return

    referenced = plugin if manifest == PLUGIN_MANIFEST else _load_json(manifest)
    if isinstance(referenced, Finding):
        yield referenced
        return

    if entry.get("name") != referenced.get("name"):
        yield Finding(MARKETPLACE_MANIFEST, f"{where}: name {entry.get('name')!r} does not "
                                            f"match the plugin manifest's "
                                            f"{referenced.get('name')!r}")
    if "version" in entry and entry["version"] != referenced.get("version"):
        yield Finding(MARKETPLACE_MANIFEST, f"{where}: version {entry['version']!r} disagrees "
                                            f"with plugin.json. Omit it here so there is one "
                                            f"source of truth")


def _load_json(path: Path) -> dict | Finding:
    if not path.is_file():
        return Finding(path, "missing")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Finding(path, f"invalid JSON: {exc}")
    except OSError as exc:
        return Finding(path, f"cannot be read: {exc}")
    if not isinstance(loaded, dict):
        return Finding(path, "must contain a JSON object")
    return loaded


PLACEHOLDER_RE = re.compile(
    r"INSERT [A-Z ]+|<[a-z-]+@[a-z.-]+>|TODO|FIXME|XXX|example\.com", re.IGNORECASE
)


def check_governance() -> Iterator[Finding]:
    """The governance files name a real contact, not a placeholder."""
    contacts = {
        REPO / "CODE_OF_CONDUCT.md": "a Code of Conduct with no route to report is decoration",
        REPO / "SECURITY.md": "a security policy with no route to report is decoration",
    }
    for path, why in contacts.items():
        if not path.is_file():
            yield Finding(path, "missing")
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = PLACEHOLDER_RE.search(line)
            if match:
                yield Finding(path, f"placeholder {match.group()!r} left in; {why}",
                              line=lineno)
        if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text) and "http" not in text:
            yield Finding(path, f"names no way to make a report; {why}")


def render_skills_table() -> str:
    rows = ["| Skill | What it is for |", "|---|---|"]
    for skill in skill_dirs():
        md = skill / "SKILL.md"
        if not md.is_file():
            continue
        try:
            meta, _ = parse(read(md))
        except (FrontmatterError, OSError):
            continue
        name = meta.get("name") or skill.name
        desc = meta.get("description")
        # First sentence keeps the table scannable; the skill carries the rest.
        summary = desc.split(". ")[0].rstrip(".").replace("|", "\\|") if isinstance(desc, str) else ""
        rows.append(f"| [`{name}`](skills/{skill.name}/SKILL.md) | {summary}. |")
    return "\n".join(rows)


def _readme_parts() -> tuple[str, str, str] | None:
    if not README.is_file():
        return None
    text = README.read_text(encoding="utf-8")
    if BEGIN_MARKER not in text or END_MARKER not in text:
        return None
    before, _, rest = text.partition(BEGIN_MARKER)
    current, _, after = rest.partition(END_MARKER)
    return before, current, after


def check_readme() -> Iterator[Finding]:
    """The generated skills table matches what the skills say."""
    if not README.is_file():
        yield Finding(README, "missing")
        return
    parts = _readme_parts()
    if parts is None:
        yield Finding(README, f"needs the markers {BEGIN_MARKER} and {END_MARKER} around "
                              f"the skills table")
        return
    _, current, _ = parts
    if current != f"\n{render_skills_table()}\n":
        yield Finding(README, "skills table is out of date. Run: make readme")


def write_readme() -> None:
    """The fixer. Separate from the check so `all` stays read-only."""
    parts = _readme_parts()
    if parts is None:
        raise SystemExit(f"README.md is missing, or lacks the {BEGIN_MARKER} / "
                         f"{END_MARKER} markers")
    before, _, after = parts
    README.write_text(f"{before}{BEGIN_MARKER}\n{render_skills_table()}\n{END_MARKER}{after}",
                      encoding="utf-8")


class Rule(NamedTuple):
    source: str
    pattern: re.Pattern[str]


class DenylistError(Exception):
    """A denylist file that will not compile. Carries where, for a Finding."""

    def __init__(self, path: Path, lineno: int, message: str):
        super().__init__(message)
        self.path = path
        self.lineno = lineno


def load_rules(name: str) -> list[Rule]:
    """Raises DenylistError rather than exiting: a bad config file is a finding,
    and exiting here would discard every finding the other checks already made."""
    path = REPO / "hack" / "denylist" / name
    if not path.is_file():
        return []
    rules = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rules.append(Rule(line, re.compile(line, re.IGNORECASE)))
        except re.error as exc:
            raise DenylistError(path, lineno, f"invalid regex {line!r}: {exc}")
    return rules


def check_hygiene() -> Iterator[Finding]:
    """No private hostnames, addresses, or key material in tracked files."""
    # strings.local.txt is gitignored, so a deployment can add its own patterns
    # without publishing its naming scheme.
    try:
        rules = load_rules("strings.txt") + load_rules("strings.local.txt")
        allowed = load_rules("strings-allow.txt") + load_rules("strings-allow.local.txt")
    except DenylistError as exc:
        yield Finding(exc.path, str(exc), line=exc.lineno)
        return
    if not rules:
        return

    tracked = git_lines("ls-files", "-z")
    if tracked is None:
        yield Finding(REPO, "cannot list tracked files -- is git installed, and is this "
                            "a checkout? The scan did not run, so this is not a pass")
        return

    # The denylist and its tests contain the patterns by definition.
    exempt = [REPO / "hack" / "denylist", REPO / "hack" / "tests"]

    for name in tracked:
        path = REPO / name
        if not path.is_file() or path.suffix in BINARY_SUFFIXES:
            continue
        if any(inside(path, d) for d in exempt):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(rule.pattern.search(line) for rule in allowed):
                continue
            for rule in rules:
                if rule.pattern.search(line):
                    yield Finding(path, f"matches denied pattern /{rule.source}/ -- "
                                        f"internal hostnames and secrets must not ship",
                                  line=lineno)
                    break


def staged_additions() -> Iterator[tuple[str, int, str]]:
    """Yield (path, line number, text) for every line a commit would add.

    Only additions, so an existing file does not re-flag on an unrelated edit.
    """
    raw = subprocess.run(
        ["git", "diff", "--cached", "--no-color", "-U0", "--diff-filter=ACMR"],
        cwd=REPO, capture_output=True, check=False,
    ).stdout.decode("utf-8", "replace")

    path = ""
    lineno = 0
    for line in raw.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            lineno = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            yield path, lineno, line[1:]
            lineno += 1


def check_secrets(staged: bool = False) -> Iterator[Finding]:
    """No credentials in tracked files, or in what is about to be committed."""
    # Two tiers. A known token format is conclusive and the allowlist cannot
    # wave it through; the heuristic is suspicious only, so it can.
    try:
        certain = load_rules("secrets.txt") + load_rules("secrets.local.txt")
        heuristic = load_rules("secrets-heuristic.txt")
        allowed = load_rules("secrets-allow.txt") + load_rules("secrets-allow.local.txt")
    except DenylistError as exc:
        yield Finding(exc.path, str(exc), line=exc.lineno)
        return
    if not certain and not heuristic:
        return
    exempt = [REPO / "hack" / "denylist", REPO / "hack" / "tests"]

    def scan(where: Path, lineno: int, text: str) -> Iterator[Finding]:
        for rule in certain:
            if rule.pattern.search(text):
                yield Finding(where, f"credential detected (/{rule.source}/). If it is "
                                     f"real, rotate it now -- once committed it is in "
                                     f"your reflog and every clone",
                              line=lineno)
                return
        if any(rule.pattern.search(text) for rule in allowed):
            return
        for rule in heuristic:
            if rule.pattern.search(text):
                yield Finding(where, f"looks like an assigned secret (/{rule.source}/). "
                                     f"Use an environment variable, or make the "
                                     f"placeholder obvious. See hack/denylist/"
                                     f"secrets-allow.txt",
                              line=lineno)
                return

    if staged:
        for name, lineno, text in staged_additions():
            path = REPO / name
            if any(inside(path, d) for d in exempt) or path.suffix in BINARY_SUFFIXES:
                continue
            yield from scan(path, lineno, text)
        return

    tracked = git_lines("ls-files", "-z")
    if tracked is None:
        yield Finding(REPO, "cannot list tracked files -- is git installed, and is this "
                            "a checkout? The scan did not run, so this is not a pass")
        return

    for name in tracked:
        path = REPO / name
        if not path.is_file() or path.suffix in BINARY_SUFFIXES:
            continue
        if any(inside(path, d) for d in exempt):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            yield from scan(path, lineno, line)


CHECKS: dict[str, Callable[[], Iterable[Finding]]] = {
    "frontmatter": check_frontmatter,
    "links": check_links,
    "scripts": check_scripts,
    "manifests": check_manifests,
    "readme": check_readme,
    "hygiene": check_hygiene,
    "secrets": check_secrets,
    "governance": check_governance,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="check", required=True, metavar="CHECK")
    for name, fn in CHECKS.items():
        check = sub.add_parser(name, help=(fn.__doc__ or "").strip())
        if name == "readme":
            check.add_argument("--fix", action="store_true",
                               help="rewrite the table in place")
        elif name == "secrets":
            check.add_argument("--staged", action="store_true",
                               help="scan what is about to be committed, for the hook")
    sub.add_parser("all", help="run every check")
    args = parser.parse_args(argv)

    if getattr(args, "fix", False):
        write_readme()

    names = list(CHECKS) if args.check == "all" else [args.check]
    staged = getattr(args, "staged", False)
    findings = [
        (name, list(check_secrets(staged=True) if name == "secrets" and staged
                    else CHECKS[name]()))
        for name in names
    ]
    findings = [(name, items) for name, items in findings if items]

    if not findings:
        print(f"ok ({len(names)} check{'s' if len(names) != 1 else ''} passed)")
        return 0

    total = 0
    for name, items in findings:
        print(f"\n{name}:", file=sys.stderr)
        for item in items:
            print(f"  {item}", file=sys.stderr)
            total += 1
    print(f"\n{total} problem{'s' if total != 1 else ''} found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
