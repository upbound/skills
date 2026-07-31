#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record what real YAML does with a corpus of frontmatter, for CI to assert against.

CI has no PyYAML, so the differential check runs here instead and the answers are
checked in as yaml_golden.json. Run `make golden` after changing the corpus;
test_frontmatter.py asserts the file is current whenever PyYAML is installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import frontmatter  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is needed to regenerate the golden file: pip install pyyaml")

GOLDEN = HERE / "yaml_golden.json"

# Anything the parser accepts must match what PyYAML returns. Rejections are
# recorded too, so the corpus also catches a rule being relaxed.
VALUES = [
    # ordinary prose
    "Plain text long enough to be a real description.",
    "A thing — with an em dash, (parens) and 'quotes'.",
    "See https://docs.upbound.io/llms.txt for more.",
    "Ends with a number 42 inline.",
    "emoji 🎉 survives",
    # quoting
    '"Do X. MANDATORY: do Y."',
    "'It''s a thing'",
    '"tab\\tseparated"',
    '"newline\\nescaped"',
    '"unicode \\u00e9"',
    # the failures that ship a dead skill
    "Do X. MANDATORY: do Y.",
    "See here:",
    '"unterminated',
    "'unterminated",
    "'It's a thing'",
    '"He said "hi""',
    "Use for X # not for Y",
    # YAML indicators
    "- foo", "@foo", "`foo`", "!Foo bar", "%foo", "? foo",
    "[x]", "{a: b}", "&anchor x", "*alias", "|", ">",
    # YAML 1.1 implicit typing
    "yes", "no", "on", "off", "true", "false", "null", "~",
    "1.0", "1:30", "0x1F", "0b101", "1_000", ".inf", ".nan", "-5", "1e3",
    # no-space edge cases that must stay strings
    "https://x.io/y#z", "trailing#hash", "a:b", "1.2.3-rc1",
]

DOCUMENTS = [
    "---\nname: a\n---\nbody\n",                 # minimal
    "---\n---\nbody\n",                          # empty frontmatter
    "---\nname: a\n\n# comment\nlicense: MIT\n---\nbody\n",
    "---\nname: a\nrefs:\n  - one.md\n  - two.md\n---\nbody\n",
    "---\nname: a\nrefs:\n---\nbody\n",          # key with no value
    "---\nname: a\n---\n# Title\n\n---\n\nmore\n",  # --- inside the body
]


def record(source: str) -> dict:
    """What PyYAML makes of one document's frontmatter."""
    entry: dict = {"src": source}
    try:
        fm, _ = frontmatter.split(source)
    except frontmatter.FrontmatterError:
        entry["yaml"] = None
        entry["yaml_rejects"] = True
        return entry
    try:
        loaded = yaml.safe_load(fm)
    except yaml.YAMLError:
        entry["yaml"] = None
        entry["yaml_rejects"] = True
        return entry
    entry["yaml"] = {} if loaded is None else loaded
    entry["yaml_rejects"] = not isinstance(entry["yaml"], dict)
    return entry


def main() -> int:
    documents = list(DOCUMENTS)
    for value in VALUES:
        documents.append(f"---\nname: a\ndescription: {value}\n---\nbody\n")
        documents.append(f"---\nname: a\nrefs:\n  - {value}\n---\nbody\n")

    corpus = [record(doc) for doc in documents]
    GOLDEN.write_text(json.dumps(corpus, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    rejected = sum(1 for e in corpus if e["yaml_rejects"])
    print(f"wrote {GOLDEN.relative_to(HERE.parent.parent)}: "
          f"{len(corpus)} documents, {rejected} that YAML rejects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
