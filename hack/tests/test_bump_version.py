# SPDX-License-Identifier: Apache-2.0
"""Tests for the version bumper.

It runs unattended on main and mutates a published artifact, so a wrong answer
ships silently. `level` and `bump` are pure, so most of this is cheap.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HACK))

import bump_version as bv  # noqa: E402

SKILL = "---\nname: {name}\ndescription: {desc}\n---\n\n# T\n\nbody\n"
DESC = "Does a thing worth describing at length. Use when asked about it."


class TestLevel(unittest.TestCase):
    def test_removed_is_major(self):
        self.assertIs(bv.Level.MAJOR, bv.level({"a", "b"}, {"a"}, True))

    def test_renamed_is_major(self):
        # A rename is a removal plus an addition; breaking wins.
        self.assertIs(bv.Level.MAJOR, bv.level({"a"}, {"b"}, True))

    def test_added_is_minor(self):
        self.assertIs(bv.Level.MINOR, bv.level({"a"}, {"a", "b"}, True))

    def test_edited_is_patch(self):
        self.assertIs(bv.Level.PATCH, bv.level({"a"}, {"a"}, True))

    def test_untouched_is_none(self):
        self.assertIsNone(bv.level({"a"}, {"a"}, False))


class TestBump(unittest.TestCase):
    def test_each_level(self):
        self.assertEqual("2.0.0", bv.bump("1.2.3", bv.Level.MAJOR))
        self.assertEqual("1.3.0", bv.bump("1.2.3", bv.Level.MINOR))
        self.assertEqual("1.2.4", bv.bump("1.2.3", bv.Level.PATCH))

    def test_rejects_non_semver(self):
        for bad in ["v1.2.3", "1.2", "", None, "1.2.3-rc1"]:
            with self.subTest(bad), self.assertRaises(ValueError):
                bv.bump(bad, bv.Level.PATCH)


class BumpRepo(unittest.TestCase):
    """Drives the real script against a throwaway git repository."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="bump-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved = (bv.REPO, bv.PLUGIN_MANIFEST)
        self.addCleanup(self._restore)

        bv.REPO = self.root
        bv.PLUGIN_MANIFEST = self.root / ".claude-plugin" / "plugin.json"
        self.write(".claude-plugin/plugin.json",
                   json.dumps({"name": "upbound", "version": "1.2.3"}) + "\n")
        self.git("init", "-q")
        for key, value in [("user.email", "t@example.com"), ("user.name", "T"),
                           ("commit.gpgsign", "false")]:
            self.git("config", key, value)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root,
                              capture_output=True, text=True, check=True).stdout

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--no-verify", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def _restore(self):
        bv.REPO, bv.PLUGIN_MANIFEST = self._saved

    def version(self):
        return json.loads(bv.PLUGIN_MANIFEST.read_text())["version"]

    def invoke(self, since, write=True):
        argv = ["bump_version.py", "--since", since] + (["--write"] if write else [])
        old = sys.argv
        sys.argv = argv
        try:
            return bv.main()
        finally:
            sys.argv = old



class TestAgainstGit(BumpRepo):
    def test_adding_a_skill_is_minor(self):
        base = self.commit("initial")
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        self.commit("add one")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("1.3.0", self.version())

    def test_editing_a_skill_is_patch(self):
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        base = self.commit("initial")
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC) + "more\n")
        self.commit("edit")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("1.2.4", self.version())

    def test_removing_a_skill_is_major(self):
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        self.write("skills/two/SKILL.md", SKILL.format(name="two", desc=DESC))
        base = self.commit("initial")
        shutil.rmtree(self.root / "skills" / "two")
        self.commit("remove two")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("2.0.0", self.version())

    def test_touching_nothing_leaves_the_version_alone(self):
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        base = self.commit("initial")
        self.write("README.md", "unrelated\n")
        self.commit("docs")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("1.2.3", self.version())

    def test_a_directory_without_a_skill_md_is_ignored(self):
        """The bug that would mint a major bump on every future push, forever."""
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        self.write("skills/wip/notes.md", "work in progress\n")
        base = self.commit("initial")
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC) + "x\n")
        self.commit("edit one")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("1.2.4", self.version(), "a stray directory must not read as removed")

    def test_non_ascii_skill_name_is_stable(self):
        self.write("skills/café/SKILL.md", SKILL.format(name="cafe", desc=DESC))
        base = self.commit("initial")
        self.write("README.md", "x\n")
        self.write("skills/café/SKILL.md", SKILL.format(name="cafe", desc=DESC) + "x\n")
        self.commit("edit")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("1.2.4", self.version(), "quotePath escaping must not fake a rename")

    def test_unknown_ref_reports_rather_than_crashing(self):
        self.commit("initial")
        self.assertEqual(2, self.invoke("0" * 40))

    def test_first_skill_when_skills_did_not_exist(self):
        base = self.commit("initial")
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        self.commit("add skills/")
        self.assertEqual(0, self.invoke(base))
        self.assertEqual("1.3.0", self.version())

    def test_without_write_the_manifest_is_untouched(self):
        base = self.commit("initial")
        self.write("skills/one/SKILL.md", SKILL.format(name="one", desc=DESC))
        self.commit("add one")
        self.assertEqual(0, self.invoke(base, write=False))
        self.assertEqual("1.2.3", self.version())


if __name__ == "__main__":
    unittest.main()
