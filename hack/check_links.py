#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that external links in the docs still resolve.

Run on a schedule, not as a pull request gate: a third-party site being briefly
unreachable must not leave a check that is permanently red and therefore ignored.

Status alone is not enough. docs.crossplane.io/llms.txt answers 200 with the site
homepage, so a naive checker passes a page that does not exist.

Usage:
    python3 hack/check_links.py            # warn, always exit 0
    python3 hack/check_links.py --strict   # exit 1 if anything failed
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TIMEOUT = 20
AGENT = "upbound-skills-link-check"

FENCE_RE = re.compile(r"^(```+|~~~+).*?^\1", re.MULTILINE | re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
URL_RE = re.compile(r"https://[^\s)>\"'\]]+")

# Placeholders and globs that appear in examples and are not addresses.
SKIP_RE = re.compile(r"example\.(com|org)|localhost|127\.0\.0\.1|\*|<|\$\{")


def urls_in(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Fenced blocks and inline code hold shell snippets like `https://*|http://*`.
    text = INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))
    return {
        url.rstrip(".,;:")
        for url in URL_RE.findall(text)
        if not SKIP_RE.search(url)
    }


class PermanentRedirects(urllib.request.HTTPRedirectHandler):
    """Follow 307/308.

    Before Python 3.11, redirect_request does not list 308 among the codes it
    will follow, so it raises instead. Passing the equivalent older code gets it
    through, which matters because plenty of sites answer 308.
    """

    def http_error_307(self, req, fp, code, msg, headers):
        return super().http_error_302(req, fp, 302, msg, headers)

    def http_error_308(self, req, fp, code, msg, headers):
        return super().http_error_301(req, fp, 301, msg, headers)


OPENER = urllib.request.build_opener(PermanentRedirects)


def check(url: str) -> str | None:
    """Return a problem description, or None when the link is fine."""
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with OPENER.open(request, timeout=TIMEOUT) as response:
            body = response.read(4096)
            if response.status != 200:
                return f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any transport failure is a warning
        return f"{type(exc).__name__}: {exc}"

    if url.endswith((".txt", ".md")) and re.search(rb"<!doctype html|<html", body, re.I):
        return "200 but serves HTML, so the page is probably gone"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when a link fails")
    args = parser.parse_args()

    listing = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=REPO,
                             capture_output=True, check=True).stdout
    files = [REPO / n for n in listing.decode().split("\0") if n]

    found: dict[str, list[str]] = {}
    for path in files:
        for url in urls_in(path):
            found.setdefault(url, []).append(str(path.relative_to(REPO)))

    problems = 0
    for url in sorted(found):
        problem = check(url)
        if problem:
            problems += 1
            where = ", ".join(sorted(found[url]))
            print(f"::warning title=Link::{url} -> {problem} ({where})")

    print(f"checked {len(found)} links, {problems} failed")
    return 1 if problems and args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
