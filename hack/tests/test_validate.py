# SPDX-License-Identifier: Apache-2.0
"""Tests for validate.py.

Every check here is exercised against input that should fail it. A check nobody
has watched fail is decoration, and this is the file that makes a green build
mean something.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Explicit, so import order does not matter. Without this, `import validate`
# resolves only as a side effect of support.py having been imported first, and
# any formatter that reorders imports breaks the suite.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import validate  # noqa: E402
from support import GOOD_SKILL, CheckCase  # noqa: E402


class TestFrontmatterCheck(CheckCase):
    def test_accepts_a_good_skill(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL})
        self.assertClean(validate.check_frontmatter())

    def test_name_must_match_directory(self):
        self.build({"skills/wrong-dir/SKILL.md": GOOD_SKILL})
        self.assertFinding(validate.check_frontmatter(), "does not match directory")

    def test_missing_skill_md(self):
        self.build({"skills/demo-skill/notes.txt": "x"})
        self.assertFinding(validate.check_frontmatter(), "no SKILL.md")

    def test_banned_key_names_the_reason(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL.replace(
            "---\n\n# Demo", "allowed-tools: Bash\n---\n\n# Demo")})
        # Materialized: checks are generators now, so a second assertion against
        # the same object would see it exhausted.
        findings = list(validate.check_frontmatter())
        self.assertFinding(findings, "'allowed-tools' is not permitted")
        self.assertFinding(findings, "Codex and Cursor ignore it")

    def test_metadata_block_rejected_as_nested_mapping(self):
        self.build({"skills/demo-skill/SKILL.md":
                    "---\nname: demo-skill\ndescription: " + "x" * 50 +
                    "\nmetadata:\n  version: 1.0.0\n---\n\n# Demo\n"})
        self.assertFinding(validate.check_frontmatter(), "nested mapping")

    def test_missing_required_key(self):
        self.build({"skills/demo-skill/SKILL.md": "---\nname: demo-skill\n---\n\n# Demo\n"})
        self.assertFinding(validate.check_frontmatter(), "missing required key 'description'")

    def test_uppercase_name(self):
        self.build({"skills/Demo/SKILL.md": GOOD_SKILL.replace("demo-skill", "Demo")})
        self.assertFinding(validate.check_frontmatter(), "lowercase kebab-case")

    def test_description_too_short(self):
        self.build({"skills/demo-skill/SKILL.md":
                    "---\nname: demo-skill\ndescription: Too short.\n---\n\n# Demo\n"})
        self.assertFinding(validate.check_frontmatter(), "minimum 40")

    def test_description_too_long(self):
        self.build({"skills/demo-skill/SKILL.md":
                    f"---\nname: demo-skill\ndescription: {'x' * 1100}\n---\n\n# Demo\n"})
        self.assertFinding(validate.check_frontmatter(), "maximum 1024")

    def test_proactively_prefix(self):
        self.build({"skills/demo-skill/SKILL.md":
                    "---\nname: demo-skill\ndescription: PROACTIVELY use this skill "
                    "when the user asks about demos and things.\n---\n\n# Demo\n"})
        self.assertFinding(validate.check_frontmatter(), "PROACTIVELY")

    def test_body_must_open_with_h1(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL.replace("# Demo Skill", "Demo")})
        self.assertFinding(validate.check_frontmatter(), "must be an H1")

    def test_license_must_match_repo(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL.replace(
            "---\n\n# Demo", "license: MIT\n---\n\n# Demo")})
        self.assertFinding(validate.check_frontmatter(), "does not match the repository license")

    def test_over_line_budget(self):
        body = "\n".join(f"line {i}" for i in range(600))
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL + body})
        self.assertFinding(validate.check_frontmatter(), "maximum 500")


class TestLinksCheck(CheckCase):
    def test_dangling_link(self):
        self.build({"skills/demo-skill/SKILL.md":
                    GOOD_SKILL + "\nSee [notes](references/missing.md).\n"})
        self.assertFinding(validate.check_links(), "does not exist")

    def test_path_escape_is_caught(self):
        """The machine check for 'must not access resources outside its directory'."""
        self.build({
            "outside.md": "secret",
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\nSee [x](../../outside.md).\n",
        })
        self.assertFinding(validate.check_links(), "resolves outside")

    def test_escape_into_a_sibling_skill_is_caught(self):
        self.build({
            "skills/other/SKILL.md": GOOD_SKILL.replace("demo-skill", "other"),
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\n[x](../other/SKILL.md)\n",
        })
        self.assertFinding(validate.check_links(), "Skills must be self-contained")

    def test_absolute_path(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL + "\n[x](/etc/hosts)\n"})
        self.assertFinding(validate.check_links(), "absolute path")

    def test_orphan_reference_file(self):
        self.build({
            "skills/demo-skill/SKILL.md": GOOD_SKILL,
            "skills/demo-skill/references/unused.md": "# Unused\n",
        })
        self.assertFinding(validate.check_links(), "never links it")

    def test_linked_reference_is_clean(self):
        self.build({
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\n- [x](references/x.md) — read when\n",
            "skills/demo-skill/references/x.md": "# X\n",
        })
        self.assertClean(validate.check_links())

    def test_backticked_paths_resolve_from_the_skill_root(self):
        """`scripts/x` inside references/ means the skill's scripts dir.

        That is how a reader takes it. Resolving it document-relative would force
        contributors to write `../scripts/x` in prose, which is wrong for the
        human even though it would satisfy a naive checker.
        """
        self.build({
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\n- [q](references/q.md) — read when\n",
            "skills/demo-skill/references/q.md": "# Q\n\nRun `scripts/do-thing`.\n",
            "skills/demo-skill/scripts/do-thing": "#!/usr/bin/env bash\ntrue\n",
        })
        self.assertClean(validate.check_links())

    def test_backticked_path_to_a_missing_script_still_fails(self):
        self.build({
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\n- [q](references/q.md) — read when\n",
            "skills/demo-skill/references/q.md": "# Q\n\nRun `scripts/absent`.\n",
        })
        self.assertFinding(validate.check_links(), "does not exist")

    def test_markdown_links_stay_document_relative(self):
        """Standard markdown semantics; only backticked prose paths are special."""
        self.build({
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\n- [a](references/a.md) — read when\n",
            "skills/demo-skill/references/a.md": "# A\n\nSee [b](b.md).\n",
            "skills/demo-skill/references/b.md": "# B\n",
        })
        findings = validate.check_links()
        self.assertFalse([f for f in findings if "does not exist" in f], findings)

    def test_external_links_are_ignored(self):
        self.build({"skills/demo-skill/SKILL.md":
                    GOOD_SKILL + "\n[docs](https://docs.upbound.io/) and [#a](#anchor)\n"})
        self.assertClean(validate.check_links())


class TestScriptsCheck(CheckCase):
    def _skill_with_script(self, body: str = "#!/usr/bin/env bash\ntrue\n"):
        return {
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\nRun `scripts/do-thing`.\n",
            "skills/demo-skill/scripts/do-thing": body,
        }

    def test_executable_and_referenced_is_clean(self):
        self.build(self._skill_with_script(), git=True,
                   executable=("skills/demo-skill/scripts/do-thing",))
        self.assertClean(validate.check_scripts())

    def test_missing_exec_bit(self):
        self.build(self._skill_with_script(), git=True)
        self.assertFinding(validate.check_scripts(), "expected 100755")

    def test_missing_shebang(self):
        self.build(self._skill_with_script("echo hi\n"), git=True,
                   executable=("skills/demo-skill/scripts/do-thing",))
        self.assertFinding(validate.check_scripts(), "no shebang")

    def test_undocumented_script(self):
        files = self._skill_with_script()
        files["skills/demo-skill/SKILL.md"] = GOOD_SKILL  # drops the mention
        self.build(files, git=True, executable=("skills/demo-skill/scripts/do-thing",))
        self.assertFinding(validate.check_scripts(), "mentions it")

    def test_gitignored_download_is_skipped(self):
        """Using a skill must not break `make check` in that checkout.

        upbound-hub downloads its credential helper into its own scripts/ and
        gitignores it. Checked, it fails three ways at once: no shebang because
        it is a binary, untracked because it is ignored, and undocumented.
        """
        files = self._skill_with_script()
        files[".gitignore"] = "skills/*/scripts/downloaded-helper\n"
        self.build(files, git=True, executable=("skills/demo-skill/scripts/do-thing",))

        # After the commit, exactly as hub-setup writes it at runtime.
        helper = self.root / "skills/demo-skill/scripts/downloaded-helper"
        helper.write_bytes(b"\x7fELF not a script")
        helper.chmod(0o755)

        self.assertClean(validate.check_scripts())

    def test_untracked_script_is_still_reported(self):
        """Skipping ignored files must not start skipping merely-forgotten ones."""
        files = self._skill_with_script()
        self.build(files, git=True, executable=("skills/demo-skill/scripts/do-thing",))
        stray = self.root / "skills/demo-skill/scripts/forgotten"
        stray.write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")
        stray.chmod(0o755)
        self.assertFinding(validate.check_scripts(), "not tracked by git")


class TestManifestsCheck(CheckCase):
    def test_clean(self):
        self.build({})
        self.assertClean(validate.check_manifests())

    def test_license_mismatch(self):
        """The bug that exists in claude-marketplace today."""
        self.build({".claude-plugin/plugin.json":
                    '{"name": "upbound", "version": "0.1.0", "license": "MIT"}'})
        self.assertFinding(validate.check_manifests(), "does not match")

    def test_non_semver_version(self):
        self.build({".claude-plugin/plugin.json": '{"name": "upbound", "version": "v1"}'})
        self.assertFinding(validate.check_manifests(), "not semver")

    def test_missing_version(self):
        self.build({".claude-plugin/plugin.json": '{"name": "upbound"}'})
        self.assertFinding(validate.check_manifests(), "version is required")

    def test_name_disagreement(self):
        self.build({".claude-plugin/marketplace.json":
                    '{"name": "upbound", "description": "d", "owner": {"name": "U"}, '
                    '"plugins": [{"name": "wrong", "source": "./", "description": "d"}]}'})
        self.assertFinding(validate.check_manifests(), "does not match the plugin manifest")

    def test_source_outside_repo(self):
        self.build({".claude-plugin/marketplace.json":
                    '{"name": "upbound", "description": "d", "owner": {"name": "U"}, '
                    '"plugins": [{"name": "upbound", "source": "../../", "description": "d"}]}'})
        self.assertFinding(validate.check_manifests(), "outside the repository")

    def test_invalid_json(self):
        self.build({".claude-plugin/plugin.json": "{nope"})
        self.assertFinding(validate.check_manifests(), "invalid JSON")


class TestReadmeCheck(CheckCase):
    HEADER = "# skills\n\n" + validate.BEGIN_MARKER + "\n" + validate.END_MARKER + "\n"

    def test_drift_is_caught(self):
        self.build({"README.md": self.HEADER, "skills/demo-skill/SKILL.md": GOOD_SKILL})
        self.assertFinding(validate.check_readme(), "out of date")

    def test_write_readme_makes_it_clean(self):
        self.build({"README.md": self.HEADER, "skills/demo-skill/SKILL.md": GOOD_SKILL})
        validate.write_readme()
        self.assertClean(validate.check_readme())
        self.assertIn("demo-skill", validate.README.read_text())

    def test_missing_markers(self):
        self.build({"README.md": "# skills\n"})
        self.assertFinding(validate.check_readme(), "needs the markers")


class TestHygieneCheck(CheckCase):
    REAL = "hack/denylist/strings.txt"

    def _with_denylist(self, files: dict[str, str], extra: str = ""):
        files = dict(files)
        # The repository's real patterns, so the tests exercise what ships.
        files[self.REAL] = (Path(__file__).resolve().parent.parent
                            / "denylist" / "strings.txt").read_text() + extra
        return files

    def test_the_real_leak_is_caught(self):
        """The exact hostname found in the skill that was ported."""
        self.build(self._with_denylist({
            "skills/demo-skill/SKILL.md":
                GOOD_SKILL + "\nSet HUB_API_URL=https://hub-api.internal.dev-x.u6d.dev\n",
        }), git=True)
        self.assertFinding(validate.check_hygiene(), "denied pattern")

    def test_private_address_is_caught(self):
        self.build(self._with_denylist({
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\nserver: 10.1.2.3\n",
        }), git=True)
        self.assertFinding(validate.check_hygiene(), "denied pattern")

    def test_private_key_header_is_caught(self):
        self.build(self._with_denylist({
            "skills/demo-skill/SKILL.md":
                GOOD_SKILL + "\n-----BEGIN RSA PRIVATE KEY-----\n",
        }), git=True)
        self.assertFinding(validate.check_hygiene(), "denied pattern")

    def test_example_hostname_is_allowed(self):
        self.build(self._with_denylist({
            "skills/demo-skill/SKILL.md":
                GOOD_SKILL + "\nexport HUB_API_URL=https://hub-api.internal.example.com\n",
        }), git=True)
        self.assertClean(validate.check_hygiene())

    def test_ordinary_local_filenames_are_not_flagged(self):
        """`.local.` as a bare pattern would fire on settings.local.json."""
        self.build(self._with_denylist({
            "skills/demo-skill/SKILL.md":
                GOOD_SKILL + "\nSee settings.local.json and CLAUDE.local.md.\n",
        }), git=True)
        self.assertClean(validate.check_hygiene())

    def test_a_local_overlay_is_layered_on(self):
        self.build(self._with_denylist({
            "hack/denylist/strings.local.txt": "acme-secret-host\n",
            "skills/demo-skill/SKILL.md": GOOD_SKILL + "\nhttps://acme-secret-host/x\n",
        }), git=True)
        self.assertFinding(validate.check_hygiene(), "denied pattern")


class TestMainAndPinnedFixes(CheckCase):
    """Pins behavior that a mutation run showed no test was protecting.

    Each of these corresponds to a fix that could be reverted with the suite
    still green, which makes the fix worth exactly nothing over time.
    """

    HEADER = "# skills\n\n" + validate.BEGIN_MARKER + "\n" + validate.END_MARKER + "\n"

    def test_all_never_writes_the_readme(self):
        """`--fix` is a separate verb; running every check must not mutate the repo."""
        self.build({"README.md": self.HEADER, "skills/demo-skill/SKILL.md": GOOD_SKILL})
        before = validate.README.read_text()
        validate.main(["all"])
        self.assertEqual(before, validate.README.read_text())

    def test_main_returns_nonzero_on_a_finding(self):
        self.build({"skills/wrong-dir/SKILL.md": GOOD_SKILL})
        self.assertEqual(1, validate.main(["frontmatter"]))

    def test_main_returns_zero_when_clean(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL})
        self.assertEqual(0, validate.main(["frontmatter"]))

    def test_fenced_examples_are_not_link_checked(self):
        """A doc about writing skills contains example links that do not resolve."""
        self.build({"skills/demo-skill/SKILL.md":
                    GOOD_SKILL + "\n```markdown\n[example](references/not-real.md)\n```\n"})
        self.assertClean(validate.check_links())

    def test_link_title_is_not_part_of_the_path(self):
        self.build({
            "skills/demo-skill/SKILL.md":
                GOOD_SKILL + '\n- [a](references/a.md "The title") — read when\n',
            "skills/demo-skill/references/a.md": "# A\n",
        })
        self.assertClean(validate.check_links())

    def test_line_budget_counts_lines_not_newlines(self):
        """A file of exactly the limit must pass; count('\\n')+1 made it fail."""
        body = "\n".join(f"line {i}" for i in range(492))
        text = GOOD_SKILL + body
        self.assertEqual(500, len(text.splitlines()))
        self.build({"skills/demo-skill/SKILL.md": text})
        self.assertClean(validate.check_frontmatter())

    def test_byte_order_mark_does_not_look_like_a_missing_fence(self):
        self.build({"skills/demo-skill/SKILL.md": "\ufeff" + GOOD_SKILL})
        self.assertClean(validate.check_frontmatter())

    def test_manifest_must_be_an_object(self):
        self.build({".claude-plugin/plugin.json": '["not", "an", "object"]'})
        self.assertFinding(validate.check_manifests(), "must contain a JSON object")

    def test_marketplace_entry_must_be_an_object(self):
        self.build({".claude-plugin/marketplace.json":
                    '{"name": "u", "description": "d", "owner": {"name": "U"}, '
                    '"plugins": ["a-string"]}'})
        self.assertFinding(validate.check_manifests(), "must be an object")

    def test_a_bad_denylist_is_a_finding_not_an_exit(self):
        """Exiting would discard the findings the other checks already made."""
        self.build({"hack/denylist/strings.txt": "# note\nfoo(unclosed\n"}, git=True)
        self.assertFinding(validate.check_hygiene(), "invalid regex")

    def test_hygiene_does_not_pass_when_git_cannot_run(self):
        self.build({"skills/demo-skill/SKILL.md": GOOD_SKILL,
                    "hack/denylist/strings.txt": "\\.internal\\.\n"})  # no git=True
        self.assertFinding(validate.check_hygiene(), "did not run")


class TestGovernanceCheck(CheckCase):
    """A policy with no route to report is decoration."""

    COC = "# CoC\n\nReport to real@example-org.test.\n"
    SEC = "# Security\n\nReport to real@example-org.test.\n"

    def test_real_contacts_pass(self):
        self.build({"CODE_OF_CONDUCT.md": self.COC, "SECURITY.md": self.SEC})
        self.assertClean(validate.check_governance())

    def test_placeholder_is_caught(self):
        for placeholder in ["[INSERT CONTACT METHOD]", "TODO: add an address",
                            "<conduct@your-org.com>"]:
            with self.subTest(placeholder):
                self.build({"CODE_OF_CONDUCT.md": f"# CoC\n\nReport to {placeholder}.\n",
                            "SECURITY.md": self.SEC})
                self.assertFinding(validate.check_governance(), "placeholder")

    def test_no_contact_at_all_is_caught(self):
        self.build({"CODE_OF_CONDUCT.md": "# CoC\n\nBe excellent to each other.\n",
                    "SECURITY.md": self.SEC})
        self.assertFinding(validate.check_governance(), "no way to make a report")

    def test_missing_file_is_caught(self):
        self.build({"SECURITY.md": self.SEC})
        self.assertFinding(validate.check_governance(), "missing")


class TestSecretsCheck(CheckCase):
    """The pre-commit credential gate. A miss ships a secret; a false positive
    blocks someone's work, so both directions are covered."""

    DENYLISTS = ("secrets.txt", "secrets-heuristic.txt", "secrets-allow.txt")

    def _repo(self, line: str):
        """A temp repo carrying the real shipped patterns plus one line of content."""
        here = Path(__file__).resolve().parent.parent / "denylist"
        files = {f"hack/denylist/{n}": (here / n).read_text() for n in self.DENYLISTS}
        files["notes.md"] = f"# Notes\n\n{line}\n"
        self.build(files, git=True)

    CERTAIN = [
        ("AWS access key", "aws_key = AKIAIOSFODNN7EXAMPLE"),
        ("GitHub token", "token: ghp_016C7e11223344556677889900aabbccddeeff"),
        ("Google API key", "key=AIzaSyD-1234567890abcdefghijklmnopqrstuv"),
        ("Anthropic key", "key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345"),
        ("Slack token", "slack: xoxb-123456789012-abcdefghijklmnop"),
        ("private key", "-----BEGIN RSA PRIVATE KEY-----"),
        ("JWT", "auth: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig"),
        ("Stripe live key", "sk_live_4eC39HqLyjWDarjtT1zdp7dc"),
    ]

    ALLOWED = [
        ("env var", 'token: "$HUB_TOKEN"'),
        ("command substitution", 'token="$(helper get-token)"'),
        ("your- placeholder", 'password = "your-password-here"'),
        ("angle placeholder", 'token: "<your-token>"'),
        ("example value", 'api_key: "example-value"'),
        ("prose", "The token is cached and refreshed automatically."),
    ]

    def test_known_token_formats_are_caught(self):
        for label, line in self.CERTAIN:
            with self.subTest(label):
                self._repo(line)
                self.assertFinding(validate.check_secrets(), "credential detected")

    def test_placeholders_and_references_are_not(self):
        for label, line in self.ALLOWED:
            with self.subTest(label):
                self._repo(line)
                self.assertClean(validate.check_secrets())

    def test_assigned_secret_is_caught_by_the_heuristic(self):
        self._repo('password = "hunter2correcthorse"')
        self.assertFinding(validate.check_secrets(), "looks like an assigned secret")

    def test_allowlist_cannot_wave_through_a_known_format(self):
        """The bug this design exists to prevent: a broad allowlist entry must
        not suppress a real AWS key just because the line says 'example'."""
        self._repo("# example config uses AKIAIOSFODNN7EXAMPL1")
        self.assertFinding(validate.check_secrets(), "credential detected")

    def test_staged_mode_sees_only_additions(self):
        self._repo('password = "hunter2correcthorse"')
        # Committed, so nothing is staged; the staged scan must be quiet even
        # though the working tree still contains the line.
        self.assertClean(validate.check_secrets(staged=True))
        self.assertFinding(validate.check_secrets(), "assigned secret")


if __name__ == "__main__":
    unittest.main()
