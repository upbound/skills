# SPDX-License-Identifier: Apache-2.0
"""Tests for the restricted frontmatter parser.

The invariant that matters is one-directional: anything this parser accepts,
real YAML must also accept, with the same values. Being stricter than YAML is
the point. A false accept is the dangerous failure, because it means a skill
passes validation and then loads with no metadata at runtime.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from frontmatter import FrontmatterError, parse, split  # noqa: E402

GOLDEN = HERE / "yaml_golden.json"

try:
    import yaml
except ImportError:  # pragma: no cover - absent in CI, by design
    yaml = None


ACCEPTED = {
    "plain scalars": "---\nname: a-b\ndescription: Does a thing. Use when asked.\n---\nbody\n",
    "double-quoted colon": '---\nname: a\ndescription: "Do X. NOTE: do Y."\n---\nb\n',
    "single-quoted colon": "---\nname: a\ndescription: 'Do X. NOTE: do Y.'\n---\nb\n",
    "block sequence": "---\nname: a\nreferences:\n  - references/x.md\n  - references/y.md\n---\nb\n",
    "em dash and parens": "---\nname: a\ndescription: A thing — a (parenthetical) one.\n---\nb\n",
    "url": "---\nname: a\ndescription: See https://x.io/y#z for more.\n---\nb\n",
    "comment line": "---\n# a note\nname: a\ndescription: thing\n---\nb\n",
    "empty body": "---\nname: a\n---\n",
}


class TestAccepted(unittest.TestCase):
    def test_parses_with_the_expected_values(self):
        # Asserting a key merely exists would pass even if every value were
        # wrong, which is how the original version of this test was useless.
        expected = {
            "plain scalars": {"name": "a-b",
                              "description": "Does a thing. Use when asked."},
            "double-quoted colon": {"name": "a", "description": "Do X. NOTE: do Y."},
            "single-quoted colon": {"name": "a", "description": "Do X. NOTE: do Y."},
            "block sequence": {"name": "a",
                               "references": ["references/x.md", "references/y.md"]},
            "em dash and parens": {"name": "a",
                                   "description": "A thing \u2014 a (parenthetical) one."},
            "url": {"name": "a", "description": "See https://x.io/y#z for more."},
            "comment line": {"name": "a", "description": "thing"},
            "empty body": {"name": "a"},
        }
        for label, text in ACCEPTED.items():
            with self.subTest(label):
                meta, _ = parse(text)
                self.assertEqual(expected[label], meta)

class TestInvariant(unittest.TestCase):
    """The one-directional invariant, checked without needing PyYAML.

    CI has no PyYAML, so generate_golden.py records what it does and this
    asserts against that. Skipping here instead would leave the property the
    module exists to guarantee unenforced exactly where it matters.
    """

    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise unittest.SkipTest(f"{GOLDEN} missing; run: make golden")
        cls.corpus = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_corpus_is_not_trivially_small(self):
        self.assertGreater(len(self.corpus), 50)
        rejected = [e for e in self.corpus if e["yaml_rejects"]]
        self.assertGreater(len(rejected), 10, "corpus must exercise rejection too")

    def test_no_false_accepts(self):
        for entry in self.corpus:
            if not entry["yaml_rejects"]:
                continue
            with self.subTest(entry["src"]):
                with self.assertRaises(
                    FrontmatterError,
                    msg=f"accepted {entry['src']!r}, which real YAML rejects",
                ):
                    parse(entry["src"])

    def test_accepted_values_match_real_yaml(self):
        for entry in self.corpus:
            if entry["yaml_rejects"]:
                continue
            with self.subTest(entry["src"]):
                try:
                    ours, _ = parse(entry["src"])
                except FrontmatterError:
                    continue  # stricter than YAML is allowed
                for key, value in ours.items():
                    self.assertEqual(
                        entry["yaml"].get(key), value,
                        f"value for {key!r} disagrees with real YAML",
                    )

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_golden_file_is_current(self):
        """Guards against the corpus drifting from what PyYAML actually does."""
        before = GOLDEN.read_text(encoding="utf-8")
        subprocess.run([sys.executable, str(HERE / "generate_golden.py")],
                       check=True, capture_output=True)
        after = GOLDEN.read_text(encoding="utf-8")
        self.assertEqual(before, after, "yaml_golden.json is stale; run: make golden")


class TestRejected(unittest.TestCase):
    def _rejects(self, text: str, needle: str):
        with self.assertRaises(FrontmatterError) as ctx:
            parse(text)
        self.assertIn(needle, str(ctx.exception))

    def test_unquoted_colon_space(self):
        """The author-tests-kcl bug: real YAML fails, and the skill silently dies."""
        text = "---\nname: a\ndescription: Do X. MANDATORY: do Y.\n---\nb\n"
        self._rejects(text, "colon followed by a space")
        if yaml is not None:
            with self.assertRaises(yaml.YAMLError):
                yaml.safe_load(split(text)[0])

    def test_trailing_colon(self):
        self._rejects("---\nname: a\ndescription: See here:\n---\nb\n", "colon")

    def test_nested_mapping(self):
        self._rejects("---\nname: a\nmetadata:\n  version: 1\n---\nb\n", "nested mapping")

    def test_flow_collection(self):
        self._rejects("---\nname: a\nreferences: [x.md]\n---\nb\n", "punctuation")

    def test_block_scalar(self):
        self._rejects("---\nname: a\ndescription: >-\n  folded\n---\nb\n", "punctuation")

    def test_anchor(self):
        self._rejects("---\nname: &a x\n---\nb\n", "punctuation")

    def test_unterminated_double_quote(self):
        """Reachable in one keystroke from the advice the colon error gives."""
        self._rejects('---\nname: a\ndescription: "Do X. NOTE: do Y.\n---\nb\n',
                      "complete double-quoted string")

    def test_unterminated_single_quote(self):
        self._rejects("---\nname: a\ndescription: 'Do X.\n---\nb\n",
                      "complete single-quoted string")

    def test_apostrophe_inside_single_quotes(self):
        self._rejects("---\nname: a\ndescription: 'It's a thing'\n---\nb\n",
                      "double any apostrophe")

    def test_inline_comment_would_truncate(self):
        self._rejects("---\nname: a\ndescription: Use for X # not for Y\n---\nb\n",
                      "comment")

    def test_implicit_boolean(self):
        self._rejects("---\nname: yes\n---\nb\n", "other than text")

    def test_implicit_number(self):
        self._rejects("---\nname: a\nversion: 1.0\n---\nb\n", "other than text")

    def test_list_items_are_validated_too(self):
        """List items bypassed every value check before this."""
        self._rejects("---\nname: a\nrefs:\n  - x: y\n---\nb\n", "colon")
        self._rejects("---\nname: a\nrefs:\n  - [x]\n---\nb\n", "punctuation")

    def test_non_breaking_space_is_diagnosed(self):
        """Invisible in an editor, and YAML rejects the whole document."""
        self._rejects("---\nname: a\n\xa0\ndescription: " + "x" * 50 + "\n---\nb\n",
                      "U+00A0")

    def test_lone_carriage_return_is_diagnosed(self):
        self._rejects("---\nname: a\ndescription: one\rtwo\n---\nb\n", "U+000D")

    def test_ragged_list_indentation(self):
        self._rejects("---\nrefs:\n    - x\n  - y\n---\nb\n", "indented")

    def test_keys_are_validated_like_values(self):
        self._rejects("---\n[a]: b\n---\nb\n", "key")
        self._rejects("---\nyes: a\n---\nb\n", "other than text")

    def test_date_shaped_value(self):
        self._rejects("---\nname: a\nreleased: 2024-01-15\n---\nb\n", "other than text")

    def test_byte_order_mark_is_diagnosed(self):
        self._rejects("\ufeff---\nname: a\n---\nb\n", "byte-order mark")

    def test_crlf_is_diagnosed(self):
        self._rejects("---\r\nname: a\r\n---\r\nb\r\n", "CRLF")

    def test_tab(self):
        self._rejects("---\nname:\ta\n---\nb\n", "tabs")

    def test_duplicate_key(self):
        self._rejects("---\nname: a\nname: b\n---\nb\n", "duplicate key")

    def test_missing_fence(self):
        self._rejects("name: a\n---\nb\n", "must open with")

    def test_unclosed_fence(self):
        self._rejects("---\nname: a\nbody text\n", "never closed")

    def test_list_item_without_key(self):
        self._rejects("---\n  - orphan\n---\nb\n", "no key above it")


class TestSplit(unittest.TestCase):
    def test_body_excludes_fence(self):
        _, body = parse("---\nname: a\n---\n# Title\n\ntext\n")
        self.assertTrue(body.startswith("# Title"))

    def test_body_keeps_later_triple_dashes(self):
        # assertIn("---", body) would pass even if body were exactly "---".
        _, body = parse("---\nname: a\n---\n# T\n\n---\n\nmore\n")
        self.assertEqual("# T\n\n---\n\nmore\n", body)

    def test_empty_frontmatter(self):
        meta, body = parse("---\n---\nbody\n")
        self.assertEqual({}, meta)
        self.assertEqual("body\n", body)

    def test_key_with_no_value_is_none(self):
        # PyYAML returns None here, not [].
        meta, _ = parse("---\nname: a\nrefs:\n---\nb\n")
        self.assertEqual({"name": "a", "refs": None}, meta)


if __name__ == "__main__":
    unittest.main()
