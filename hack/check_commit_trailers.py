#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check commit messages for DCO sign-off and banned co-author identities.

Rule 2 is an identity denylist, not a ban on the Co-authored-by trailer, which
GitHub adds legitimately for humans on squash merges. The pull request body is
checked as well, since GitHub composes the squash-merge message from it.

Usage:
    python3 hack/check_commit_trailers.py --range origin/main..HEAD
    python3 hack/check_commit_trailers.py --all
    python3 hack/check_commit_trailers.py --message-file .git/COMMIT_EDITMSG
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

REPO = Path(__file__).resolve().parent.parent
DENYLIST = REPO / "hack" / "denylist" / "coauthors.txt"
ALLOWLIST = REPO / "hack" / "denylist" / "coauthors-allow.txt"

COAUTHOR_RE = re.compile(r"^\s*co-authored-by:\s*(.+?)\s*$", re.IGNORECASE)
SIGNOFF_RE = re.compile(r"^\s*signed-off-by:\s*(.+?)\s*$", re.IGNORECASE)
IDENTITY_RE = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^>]*)>\s*$")
GENERATED_RE = re.compile(
    r"generated[-\s]with:?\s*\[?(claude|codex|cursor|copilot|gemini|devin|chatgpt)",
    re.IGNORECASE,
)

# Bots cannot sign the DCO, and their commits are mechanical. Exempt from
# sign-off, still subject to the co-author rules.
BOT_AUTHOR_RE = re.compile(
    r"(\[bot\]@users\.noreply\.github\.com|^dependabot|^renovate)", re.IGNORECASE
)

FIX_HINT = """
To fix, reword the offending commits:

    git rebase -i origin/main

or, for a single-commit branch:

    git reset --soft origin/main && git commit -s

If the trailer names a real person or a bot this project wants credited, add the
identity to hack/denylist/coauthors-allow.txt in this pull request and say why.
See CONTRIBUTING.md.
"""


class Rule(NamedTuple):
    source: str
    pattern: re.Pattern[str]


class Commit(NamedTuple):
    sha: str
    author_email: str
    message: str


def load_rules(path: Path) -> list[Rule]:
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
            raise SystemExit(f"{path}:{lineno}: invalid regex {line!r}: {exc}")
    return rules


def git(*args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, check=True
        ).stdout
    except FileNotFoundError:
        raise SystemExit("error: git is not installed or not on PATH")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise SystemExit(f"error: git failed: {detail}")


def commits(rev_range: str | None, everything: bool) -> list[Commit]:
    # -z separates on NUL, which a commit message cannot contain. A printable
    # separator would desynchronize and silently drop that commit.
    args = ["log", "-z", "--no-merges", "--format=%H %ae%n%B"]
    raw = git(*args) if everything else git(*args, rev_range)

    out = []
    for record in raw.decode("utf-8", "replace").split("\0"):
        if not record.strip():
            continue
        header, _, message = record.partition("\n")
        sha, _, email = header.partition(" ")
        out.append(Commit(sha.strip(), email.strip(), message))
    return out


def banned_coauthors(lines: Iterable[str], denied: list[Rule],
                     allowed: list[Rule]) -> list[tuple[str, str]]:
    found = []
    for line in lines:
        match = COAUTHOR_RE.match(line)
        if not match:
            continue
        identity = match.group(1)
        if any(rule.pattern.search(identity) for rule in allowed):
            continue

        parsed = IDENTITY_RE.match(identity)
        name = (parsed.group("name") if parsed else identity).strip()
        email = (parsed.group("email") if parsed else "").strip()

        for rule in denied:
            if rule.pattern.search(name) or (email and rule.pattern.search(email)):
                found.append((line.strip(), rule.source))
                break
    return found


def check_message(message: str, denied: list[Rule], allowed: list[Rule],
                  require_signoff: bool) -> list[str]:
    lines = message.splitlines()
    problems = [
        f"banned co-author trailer (matched /{source}/): {trailer}"
        for trailer, source in banned_coauthors(lines, denied, allowed)
    ]
    problems += [
        f"generated-with attribution: {line.strip()}"
        for line in lines
        if GENERATED_RE.search(line)
        and not any(rule.pattern.search(line) for rule in allowed)
    ]
    if require_signoff and not any(SIGNOFF_RE.match(line) for line in lines):
        problems.append("no Signed-off-by trailer; commit with `git commit -s`")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--range", dest="rev_range", help="e.g. origin/main..HEAD")
    group.add_argument("--all", action="store_true", help="every commit in history")
    group.add_argument("--message-file", type=Path, help="a single message, for the hook")
    parser.add_argument("--pr-body-file", type=Path,
                        help="pull request body, which becomes the squash-merge message")
    parser.add_argument("--no-signoff", action="store_true",
                        help="skip the DCO check; the trailer check still runs")
    args = parser.parse_args(argv)

    denied = load_rules(DENYLIST)
    allowed = load_rules(ALLOWLIST)
    if not denied:
        print(f"error: {DENYLIST} is missing or empty", file=sys.stderr)
        return 2

    require_signoff = not args.no_signoff
    failures: list[tuple[str, list[str]]] = []

    if args.message_file:
        try:
            text = args.message_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"error: cannot read {args.message_file}: {exc}", file=sys.stderr)
            return 2
        # The hook runs before a sign-off is necessarily present, so only the
        # trailer rules apply here.
        problems = check_message(text, denied, allowed, require_signoff=False)
        if problems:
            failures.append(("(this commit)", problems))
    else:
        for commit in commits(args.rev_range, args.all):
            needs_signoff = require_signoff and not BOT_AUTHOR_RE.search(commit.author_email)
            problems = check_message(commit.message, denied, allowed, needs_signoff)
            if problems:
                subject = commit.message.splitlines()[0] if commit.message.strip() else ""
                failures.append((f"{commit.sha[:12]}  {subject[:60]}", problems))

    if args.pr_body_file and args.pr_body_file.is_file():
        body = args.pr_body_file.read_text(encoding="utf-8", errors="replace")
        problems = check_message(body, denied, allowed, require_signoff=False)
        if problems:
            failures.append(("(pull request body -- becomes the squash-merge message)",
                             problems))

    if not failures:
        return 0

    print("Commit trailer check failed.\n", file=sys.stderr)
    for where, problems in failures:
        print(f"  {where}", file=sys.stderr)
        for problem in problems:
            print(f"      {problem}", file=sys.stderr)
        print(file=sys.stderr)
    print(FIX_HINT.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
