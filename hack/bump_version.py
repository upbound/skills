#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Work out the version bump a change to skills/ deserves, and apply it.

Skill directory names are the invocation surface, so removing or renaming one is
breaking: removed -> major, added -> minor, edited -> patch. Run by
.github/workflows/bump.yml after a merge to main.

Usage:
    python3 hack/bump_version.py --since <ref>
    python3 hack/bump_version.py --since <ref> --write
"""

from __future__ import annotations

import argparse
import enum
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_MANIFEST = REPO / ".claude-plugin" / "plugin.json"
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class Level(enum.Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def rev_exists(ref: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=REPO, capture_output=True,
    ).returncode == 0


def skill_names(ref: str | None = None) -> set[str]:
    """Directory names under skills/ that contain a SKILL.md.

    Both branches must apply the same rule. Counting every directory at `ref` but
    only SKILL.md-bearing ones in the working tree makes any other directory look
    permanently removed, which mints a major bump on every future push.
    """
    if ref is None:
        root = REPO / "skills"
        if not root.is_dir():
            return set()
        return {p.name for p in root.iterdir() if (p / "SKILL.md").is_file()}

    # -z avoids core.quotePath mangling non-ASCII names into \303\251 escapes,
    # which would make the same skill look both removed and added.
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", f"{ref}:skills"],
        cwd=REPO, capture_output=True, check=True,
    ).stdout.decode("utf-8", "surrogateescape")

    return {
        name.split("/", 1)[0]
        for name in listing.split("\0")
        if name.count("/") == 1 and name.endswith("/SKILL.md")
    }


def level(before: set[str], after: set[str], changed: bool) -> Level | None:
    """None means nothing to do, which is not an error."""
    if before - after:
        return Level.MAJOR
    if after - before:
        return Level.MINOR
    return Level.PATCH if changed else None


def bump(version: str, how: Level) -> str:
    match = SEMVER_RE.match(version or "")
    if not match:
        raise ValueError(f"{version!r} is not semver")
    major, minor, patch = (int(g) for g in match.groups())
    return {
        Level.MAJOR: f"{major + 1}.0.0",
        Level.MINOR: f"{major}.{minor + 1}.0",
        Level.PATCH: f"{major}.{minor}.{patch + 1}",
    }[how]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--since", required=True, help="the ref to compare against")
    parser.add_argument("--write", action="store_true", help="update plugin.json")
    args = parser.parse_args()

    if not rev_exists(args.since):
        print(f"error: {args.since!r} is not a commit here. A force-push or a "
              f"shallow clone would explain it.", file=sys.stderr)
        return 2

    try:
        before = skill_names(args.since)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
        if "Not a valid object name" not in stderr and "does not exist" not in stderr:
            print(f"error: git ls-tree failed: {stderr.strip()}", file=sys.stderr)
            return 2
        before = set()  # skills/ did not exist at that ref

    after = skill_names()
    changed = bool(git("diff", "--name-only", f"{args.since}..HEAD", "--", "skills").strip())

    how = level(before, after, changed)
    if how is None:
        print("no skill changes; nothing to bump", file=sys.stderr)
        return 0

    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    current = manifest.get("version")
    try:
        new = bump(current, how)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"{how.value}: {current} -> {new}  "
          f"(added: {', '.join(sorted(after - before)) or 'none'}; "
          f"removed: {', '.join(sorted(before - after)) or 'none'})", file=sys.stderr)

    if args.write:
        manifest["version"] = new
        PLUGIN_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
