# SPDX-License-Identifier: Apache-2.0
"""Differential fuzzing of the frontmatter parser against real YAML.

Skipped without PyYAML, so CI relies on the golden corpus instead. This is the
dev-machine pass that finds what a fixed corpus cannot.

An earlier fuzzer ran 40,000 documents and found nothing, because it varied the
value alphabet while holding the document skeleton fixed and drew only from
ASCII. Every bug that survived it lived somewhere else: non-ASCII whitespace,
indentation, key position, and date-shaped values. So this one varies structure
and includes the whitespace characters YAML disagrees with Python about.
"""

from __future__ import annotations

import random
import string
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from frontmatter import FrontmatterError, parse, split  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover - absent in CI, by design
    yaml = None

# Includes the whitespace Python strips but YAML does not, which is where the
# realistic failure lives: a pasted description carries U+00A0.
ALPHABET = list(
    string.ascii_letters + string.digits + " .:#\"'-[]{}&*!|>%@`?,~\\/"
) + ["\xa0", " ", " ", "\x85", "　", "\r", "\x0b", "\x0c"]

KEYS = ["name", "description", "refs", "license", "a"]


def a_value(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.08:  # date and time shapes, which YAML resolves to objects
        return rng.choice(["2024-01-15", "2024-1-5 10:30:00", "2024-01-15T10:30:00Z", "="])
    if roll < 0.16:  # implicit non-strings
        return rng.choice(["yes", "no", "null", "~", "1.0", "0x1F", "1:30", ".inf"])
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 14)))


def a_document(rng: random.Random) -> str:
    """A frontmatter document with randomized structure, not just values."""
    lines = []
    for _ in range(rng.randint(1, 4)):
        roll = rng.random()
        if roll < 0.12:  # a blank-ish line, sometimes carrying odd whitespace
            lines.append(rng.choice(["", " ", "\xa0", "  ", "　"]))
        elif roll < 0.22:  # a comment, sometimes indented oddly
            lines.append(rng.choice(["# note", "  # note", "\xa0# note"]))
        elif roll < 0.45:  # a list, with deliberately ragged indentation
            lines.append(f"{rng.choice(KEYS)}:")
            for _ in range(rng.randint(1, 3)):
                lines.append(" " * rng.choice([0, 2, 4, 6]) + "- " + a_value(rng))
        else:  # a key, sometimes indented or oddly prefixed
            prefix = rng.choice(["", "", "", " ", "  ", "\xa0"])
            lines.append(f"{prefix}{rng.choice(KEYS)}: {a_value(rng)}")
    return "---\n" + "\n".join(lines) + "\n---\nbody\n"


@unittest.skipIf(yaml is None, "PyYAML not installed")
class TestDifferentialFuzz(unittest.TestCase):
    ROUNDS = 20000

    def test_never_accepts_what_yaml_rejects(self):
        rng = random.Random(20260730)
        accepted = 0
        for _ in range(self.ROUNDS):
            doc = a_document(rng)
            try:
                ours, _ = parse(doc)
            except FrontmatterError:
                continue
            accepted += 1

            try:
                reference = yaml.safe_load(split(doc)[0])
            except FrontmatterError:
                self.fail(f"parse() accepted a document split() rejects: {doc!r}")
            except yaml.YAMLError:
                self.fail(f"false accept -- real YAML rejects this:\n{doc!r}\ngot {ours!r}")

            # PyYAML returns None for frontmatter that is empty or only
            # comments; we return {}. Both mean "no keys", and the validator
            # treats them identically, so normalize rather than fail. Anything
            # else non-mapping is a genuine false accept.
            if reference is None:
                reference = {}
            self.assertIsInstance(
                reference, dict, f"we accept a non-mapping document:\n{doc!r}"
            )
            for key, value in ours.items():
                self.assertEqual(
                    reference.get(key), value,
                    f"value for {key!r} disagrees with real YAML:\n{doc!r}",
                )

        # A fuzzer that rejects everything proves nothing.
        self.assertGreater(accepted, self.ROUNDS // 20,
                           "corpus is too hostile to be meaningful")


if __name__ == "__main__":
    unittest.main()
