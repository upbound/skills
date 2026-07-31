# SPDX-License-Identifier: Apache-2.0
"""Build a throwaway repository so checks can be run against known-bad input.

Each test states the broken input inline rather than pointing at a fixture
directory. A test you can read top to bottom is worth more than a tidy tree.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HACK))

import validate  # noqa: E402

APACHE_LICENSE = "Apache License\nVersion 2.0, January 2004\n"

PLUGIN_JSON = """{
  "name": "upbound",
  "version": "0.1.0",
  "license": "Apache-2.0"
}
"""

MARKETPLACE_JSON = """{
  "name": "upbound",
  "description": "test",
  "owner": {"name": "Upbound"},
  "plugins": [{"name": "upbound", "source": "./", "description": "test"}]
}
"""

GOOD_SKILL = """---
name: demo-skill
description: Query demo things and report on them. Use when the user asks about demos.
---

# Demo Skill

Body.
"""


class CheckCase(unittest.TestCase):
    """Runs validate.py's checks against a temp repo built per test."""

    def setUp(self) -> None:
        # Resolved, because on macOS mkdtemp hands back /var/... which is a
        # symlink to /private/var/... and every containment check would misfire.
        self.root = Path(tempfile.mkdtemp(prefix="skills-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved = (validate.REPO, validate.SKILLS,
                       validate.PLUGIN_MANIFEST, validate.MARKETPLACE_MANIFEST,
                       validate.README)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        (validate.REPO, validate.SKILLS, validate.PLUGIN_MANIFEST,
         validate.MARKETPLACE_MANIFEST, validate.README) = self._saved

    def build(self, files: dict[str, str], *, git: bool = False,
              executable: tuple[str, ...] = ()) -> Path:
        """Write `files` (path -> contents) into the temp repo and point validate at it."""
        base = {
            "LICENSE": APACHE_LICENSE,
            ".claude-plugin/plugin.json": PLUGIN_JSON,
            ".claude-plugin/marketplace.json": MARKETPLACE_JSON,
        }
        base.update(files)

        for name, content in base.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        for name in executable:
            (self.root / name).chmod(0o755)

        validate.REPO = self.root
        validate.SKILLS = self.root / "skills"
        validate.PLUGIN_MANIFEST = self.root / ".claude-plugin" / "plugin.json"
        validate.MARKETPLACE_MANIFEST = self.root / ".claude-plugin" / "marketplace.json"
        validate.README = self.root / "README.md"
        # Cached across calls, so a stale answer would leak between temp repos.
        validate.detect_license.cache_clear()

        if git:
            self._git_init()
        return self.root

    def _git_init(self) -> None:
        run = lambda *a: subprocess.run(  # noqa: E731
            a, cwd=self.root, capture_output=True, check=True
        )
        run("git", "init", "-q")
        run("git", "config", "user.email", "test@example.com")
        run("git", "config", "user.name", "Test")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "fixture", "--no-verify")

    def assertFinding(self, findings, needle: str) -> None:
        rendered = [str(f) for f in findings]
        self.assertTrue(
            any(needle in f for f in rendered),
            f"expected a finding containing {needle!r}, got:\n"
            f"{chr(10).join(rendered) or '  (none)'}",
        )

    def assertClean(self, findings) -> None:
        rendered = [str(f) for f in findings]
        self.assertEqual([], rendered, f"expected no findings, got:\n{chr(10).join(rendered)}")
