# SPDX-License-Identifier: Apache-2.0
"""Tests for the commit trailer check.

The two failure modes that matter are opposite in direction. Missing a model
trailer defeats the point of the check. Firing on a real human breaks normal
collaboration, since GitHub adds Co-authored-by automatically on squash merges
and accepted review suggestions. Both are covered.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HACK))

import check_commit_trailers as cct  # noqa: E402

DENIED = cct.load_rules(HACK / "denylist" / "coauthors.txt")
ALLOWED = cct.load_rules(HACK / "denylist" / "coauthors-allow.txt")


def problems(message: str, require_signoff: bool = False) -> list[str]:
    return cct.check_message(message, DENIED, ALLOWED, require_signoff)


def commit(*trailers: str) -> str:
    return "feat: do a thing\n\n" + "\n".join(trailers) + "\n"


class TestBannedIdentities(unittest.TestCase):
    """Every one of these appears verbatim in upbound/claude-marketplace history."""

    CASES = [
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>",
        "Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>",
        "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>",
        "Co-authored-by: cubic-dev-ai[bot] <191113872+cubic-dev-ai[bot]@users.noreply.github.com>",
        "Co-authored-by: Copilot <copilot@github.com>",
        "Co-authored-by: Cursor Agent <agent@cursor.com>",
        "Co-authored-by: ChatGPT <noreply@openai.com>",
        "Co-authored-by: Devin <devin@cognition.ai>",
        "co-authored-by: claude <noreply@anthropic.com>",
        # Subdomain email, and vendor-plus-product name pairs.
        "Co-authored-by: AI Helper <bot@api.anthropic.com>",
        "Co-authored-by: Anthropic Claude <a@b.com>",
        "Co-authored-by: Google Gemini <g@example.com>",
    ]

    def test_all_caught(self):
        for trailer in self.CASES:
            with self.subTest(trailer):
                self.assertTrue(problems(commit(trailer)),
                                f"not caught: {trailer}")

    def test_generated_with_footer(self):
        for line in ["🤖 Generated with [Claude Code](https://claude.com/claude-code)",
                     "Generated-with: Claude Code",
                     "Generated with Codex"]:
            with self.subTest(line):
                self.assertTrue(problems(f"feat: x\n\n{line}\n"))


class TestHumansAreNotCaught(unittest.TestCase):
    """A false positive here breaks squash merges and review suggestions."""

    CASES = [
        "Co-authored-by: Ada Lovelace <ada@example.com>",
        # Names that start with a denied substring but are people.
        "Co-authored-by: Claudia Fernandez <claudia@example.com>",
        "Co-authored-by: Claudette Colvin <cc@example.com>",
        "Co-authored-by: Amparo Ruiz <amparo@example.com>",
        "Co-authored-by: Jordan Cursoria <jc@example.com>",
        # Model names that are also human names, which is why the denylist
        # requires a whole-name match, a qualifier, or a bot marker.
        "Co-authored-by: Claude Monet <claude.monet@example.com>",
        "Co-authored-by: Gemini Ortiz <gortiz@example.com>",
        "Co-authored-by: Devin Nunes <dnunes@example.com>",
        "Co-authored-by: Jules Verne <jverne@example.com>",
        "Co-authored-by: Cody Rhodes <crhodes@example.com>",
        "Co-authored-by: Amp Rutherford <amp.r@example.com>",
    ]

    def test_none_caught(self):
        for trailer in self.CASES:
            with self.subTest(trailer):
                self.assertEqual([], problems(commit(trailer)),
                                 f"false positive on a human: {trailer}")


class TestSignoff(unittest.TestCase):
    def test_missing_signoff_is_caught(self):
        self.assertTrue(problems("feat: x\n", require_signoff=True))

    def test_present_signoff_passes(self):
        msg = commit("Signed-off-by: Ada Lovelace <ada@example.com>")
        self.assertEqual([], problems(msg, require_signoff=True))

    def test_signoff_is_never_mistaken_for_a_coauthor(self):
        """Scoping to ^Co-authored-by matters; these must not trip the denylist."""
        for trailer in [
            "Signed-off-by: Claude Monet <claude@example.com>",
            "Signed-off-by: Ada Lovelace <ada@example.com>",
        ]:
            with self.subTest(trailer):
                self.assertEqual([], problems(commit(trailer), require_signoff=True))


class TestAllowlist(unittest.TestCase):
    def test_allowlist_exempts_a_named_bot(self):
        allowed = ALLOWED + [cct.Rule("cubic-dev-ai", re.compile("cubic-dev-ai"))]
        msg = commit("Co-authored-by: cubic-dev-ai[bot] "
                     "<1+cubic-dev-ai[bot]@users.noreply.github.com>")
        self.assertEqual([], cct.check_message(msg, DENIED, allowed, False))

    def test_allowlist_exempts_a_quoted_policy_line(self):
        """A doc explaining the rule must not be unmergeable because of it."""
        allowed = ALLOWED + [cct.Rule("explains the policy", re.compile("explains the policy"))]
        msg = "docs: x\n\nThis explains the policy on 'Generated with [Claude Code]'.\n"
        self.assertEqual([], cct.check_message(msg, DENIED, allowed, False))


class TestBotSignoffExemption(unittest.TestCase):
    """Bots cannot sign the DCO, so Dependabot is exempt from sign-off but still
    subject to the co-author rules.

    Exercised through main() against a real repository. Asserting on the regex
    constant would keep passing even if main() stopped applying the exemption.
    """

    BOTS = [
        "49699333+dependabot[bot]@users.noreply.github.com",
        "29139614+renovate[bot]@users.noreply.github.com",
        "1+upbound-skills-bot[bot]@users.noreply.github.com",
    ]
    HUMANS = ["ada@example.com", "taylor@upbound.io"]

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="trailer-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved = cct.REPO
        self.addCleanup(lambda: setattr(cct, "REPO", self._saved))
        cct.REPO = self.root
        self._git("init", "-q")
        self._git("config", "commit.gpgsign", "false")
        # A signed-off base commit, so tests can reset back to a passing state.
        self._commit_as("base@example.com",
                        "chore: base\n\nSigned-off-by: Base <base@example.com>")
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root,
                                   capture_output=True, text=True, check=True).stdout.strip()

    def _git(self, *args, env=None):
        subprocess.run(["git", *args], cwd=self.root, capture_output=True,
                       check=True, env=env)

    def _commit_as(self, email, message):
        env = {**os.environ, "GIT_AUTHOR_NAME": "X", "GIT_AUTHOR_EMAIL": email,
               "GIT_COMMITTER_NAME": "X", "GIT_COMMITTER_EMAIL": email}
        (self.root / "f.txt").write_text(email + message)
        self._git("add", "-A", env=env)
        self._git("commit", "-q", "--no-verify", "-m", message, env=env)

    def test_bot_commit_without_signoff_passes(self):
        for email in self.BOTS:
            with self.subTest(email):
                self._commit_as(email, f"chore: bump {email}")
                self.assertEqual(0, cct.main(["--all"]))

    def test_human_commit_without_signoff_fails(self):
        for email in self.HUMANS:
            with self.subTest(email):
                self._commit_as(email, f"feat: thing {email}")
                self.assertEqual(1, cct.main(["--all"]))
                self._git("reset", "-q", "--hard", self.base)

    def test_bot_is_still_subject_to_the_coauthor_rules(self):
        self._commit_as(self.BOTS[0],
                        "chore: x\n\nCo-authored-by: Claude <noreply@anthropic.com>")
        self.assertEqual(1, cct.main(["--all"]))


class TestDenylistFileItself(unittest.TestCase):
    def test_loads_and_is_not_empty(self):
        self.assertGreater(len(DENIED), 5)

    def test_a_bad_pattern_is_reported_with_its_line(self):
        bad = pathlib.Path(tempfile.mkdtemp()) / "bad.txt"
        bad.write_text("# note\nfoo(unclosed\n")
        with self.assertRaises(SystemExit) as ctx:
            cct.load_rules(bad)
        self.assertIn(":2:", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
