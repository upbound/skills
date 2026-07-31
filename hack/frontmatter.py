# SPDX-License-Identifier: Apache-2.0
"""A deliberately small YAML frontmatter parser: flat scalars and plain lists.

The narrow subset is what every agent's YAML reader handles identically, so
frontmatter that parses here behaves the same everywhere. It also means no
third-party dependency, so CI runs on a bare python3.

The invariant: anything this accepts, real YAML must also accept, with the same
value. Stricter is fine; laxer is a bug, because it means a skill passes
validation and then loads with empty metadata at runtime. Hence a whitelist --
an unrecognised shape is rejected, not waved through.
"""

from __future__ import annotations

import re

__all__ = ["FrontmatterError", "parse", "split"]


class FrontmatterError(Exception):
    """Frontmatter that is missing, malformed, or outside the portable subset."""


_FENCE = "---"

# YAML's whitespace is space and tab; str.strip() also eats NBSP, NEL, LS and PS.
# A pasted description carries NBSP, which is invisible in an editor and makes
# YAML reject the document while a Python-stripping parser accepts it.
_ODD_SPACE = re.compile(r"[^\S \t\n]")

# A plain scalar may not start with any of these.
_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"

# Shapes YAML 1.1 resolves to something that is not a string. `name: yes` is a
# bool, `version: 1.0` a float, `at: 1:30` the integer 90.
_IMPLICIT_NONSTRING = re.compile(
    r"""^(?:
          ~ | null|Null|NULL
        | true|True|TRUE|false|False|FALSE
        | yes|Yes|YES|no|No|NO|on|On|ON|off|Off|OFF
        | [-+]?0x[0-9a-fA-F_]+ | [-+]?0b[01_]+ | [-+]?0o?[0-7_]+
        | [-+]?\d[\d_]*(?::[0-5]?\d)*
        | [-+]?(?:\.\d+|\d[\d_]*\.\d*)(?:[eE][-+]?\d+)?
        | [-+]?\.(?:inf|Inf|INF) | \.(?:nan|NaN|NAN)
        | =
        | \d{4}-\d{2}-\d{2}
        | \d{4}-\d{1,2}-\d{1,2}(?:[Tt]|[ \t]+)\d{1,2}:\d{2}:\d{2}
          (?:\.\d*)?(?:[ \t]*(?:Z|[-+]\d{1,2}(?::\d{2})?))?
        )$""",
    re.VERBOSE,
)

# A complete double-quoted string, with only escapes YAML actually defines.
_DQUOTED = re.compile(r'^"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"$')
# A complete single-quoted string. Inside them, '' is a literal apostrophe.
_SQUOTED = re.compile(r"^'(?:[^']|'')*'$")

_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/",
    "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
}


def _unescape_double(body: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            out.append(char)
            i += 1
            continue
        marker = body[i + 1]
        if marker == "u":
            out.append(chr(int(body[i + 2 : i + 6], 16)))
            i += 6
        else:
            out.append(_ESCAPES[marker])
            i += 2
    return "".join(out)


def _scalar(value: str, lineno: int, what: str) -> str:
    """Validate one plain or quoted scalar, returning the value YAML would give.

    Raises FrontmatterError for anything outside the portable subset, with the
    remediation in the message.
    """
    if value.startswith('"'):
        if not _DQUOTED.fullmatch(value):
            raise FrontmatterError(
                f"line {lineno}: {what} is not a complete double-quoted string. "
                f'Close the quote, and escape any inner quote as \\". An '
                f"unterminated quote is read as plain text by this parser but "
                f"rejected by YAML, so the skill would load with no metadata"
            )
        return _unescape_double(value[1:-1])

    if value.startswith("'"):
        if not _SQUOTED.fullmatch(value):
            raise FrontmatterError(
                f"line {lineno}: {what} is not a complete single-quoted string. "
                f"Close the quote, and double any apostrophe inside it: 'It''s'"
            )
        return value[1:-1].replace("''", "'")

    if value[0] in _INDICATORS:
        raise FrontmatterError(
            f"line {lineno}: {what} starts with {value[0]!r}, which YAML reads as "
            f"punctuation rather than text. Quote the value"
        )

    if " #" in value:
        raise FrontmatterError(
            f"line {lineno}: {what} contains ' #', which YAML treats as the start "
            f"of a comment and silently truncates. Quote the value"
        )

    if ": " in value or value.endswith(":"):
        raise FrontmatterError(
            f"line {lineno}: {what} contains a colon followed by a space, which "
            f"YAML reads as a nested key. Quote the value or rephrase it. Left "
            f"unquoted the skill loads with no metadata and can never trigger"
        )

    if _IMPLICIT_NONSTRING.match(value):
        raise FrontmatterError(
            f"line {lineno}: YAML reads {value!r} as something other than text -- a "
            f"boolean, number, or date. Quote it to keep it a string"
        )

    return value


def split(text: str) -> tuple[str, str]:
    """Return (frontmatter_source, body) for a document opening with a fence.

    Raises FrontmatterError when the document does not open with a fence, or the
    fence is never closed.
    """
    # A byte-order mark before the fence is invisible in an editor, so diagnose
    # it rather than reporting a missing fence.
    if text.startswith("﻿"):
        raise FrontmatterError(
            "file starts with a byte-order mark; save it as UTF-8 without a BOM"
        )
    if "\r\n" in text.split("\n---", 1)[0]:
        raise FrontmatterError(
            "frontmatter uses CRLF line endings; save the file with LF endings"
        )

    if not text.startswith(_FENCE + "\n"):
        raise FrontmatterError("file must open with a '---' frontmatter fence on line 1")

    rest = text[len(_FENCE) + 1 :]

    # An immediately closing fence means empty frontmatter, which the loop below
    # cannot see because it searches for a *preceding* newline.
    if rest.startswith(_FENCE + "\n"):
        return "", rest[len(_FENCE) + 1 :]
    if rest.rstrip("\n") == _FENCE:
        return "", ""

    marker = "\n" + _FENCE
    search_from = 0
    while True:
        idx = rest.find(marker, search_from)
        if idx == -1:
            raise FrontmatterError("frontmatter fence is never closed with '---'")
        after = idx + len(marker)
        # The closing fence has to be alone on its line.
        if after == len(rest):
            return rest[:idx], ""
        if rest[after] == "\n":
            return rest[:idx], rest[after + 1 :]
        search_from = after


def parse(text: str) -> tuple[dict[str, str | list[str] | None], str]:
    """Parse a document's frontmatter. Returns (mapping, body).

    Values are strings, lists of strings for block sequences, or None for a key
    with no value -- matching what PyYAML returns for each shape.
    """
    source, body = split(text)

    odd = _ODD_SPACE.search(source)
    if odd:
        raise FrontmatterError(
            f"frontmatter contains {odd.group()!r} (U+{ord(odd.group()):04X}), which "
            f"YAML does not treat as a space. Replace it with a plain space -- it is "
            f"invisible in an editor, and YAML would reject the whole document"
        )

    out: dict[str, str | list[str] | None] = {}
    current_key: str | None = None
    list_indent: int | None = None

    # Line 1 is the opening fence, so content starts at line 2. Stripping only
    # space, never str.strip(), so this agrees with YAML about what whitespace is.
    for offset, line in enumerate(source.split("\n")):
        lineno = offset + 2

        if "\t" in line:
            raise FrontmatterError(f"line {lineno}: tabs are not allowed in YAML; use spaces")
        if not line.strip(" ") or line.lstrip(" ").startswith("#"):
            continue

        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)

        if stripped.startswith("- "):
            if current_key is None:
                raise FrontmatterError(f"line {lineno}: list item with no key above it")
            if out[current_key] is None:
                out[current_key] = []
                list_indent = indent
            existing = out[current_key]
            if not isinstance(existing, list):
                raise FrontmatterError(
                    f"line {lineno}: {current_key!r} already has a value, so it "
                    f"cannot also be a list"
                )
            if indent != list_indent:
                raise FrontmatterError(
                    f"line {lineno}: list item is indented {indent} spaces but the "
                    f"list starts at {list_indent}; YAML reads a mismatched item as "
                    f"a continuation of the one before it"
                )
            item = stripped[2:].strip(" ")
            if not item:
                raise FrontmatterError(f"line {lineno}: empty list item")
            existing.append(_scalar(item, lineno, "list item"))
            continue

        if indent:
            raise FrontmatterError(
                f"line {lineno}: indented keys mean a nested mapping, which is not "
                f"portable; keep frontmatter flat"
            )

        key, sep, value = line.partition(":")
        if not sep:
            raise FrontmatterError(f"line {lineno}: expected 'key: value'")
        key = key.strip(" ")
        if not key:
            raise FrontmatterError(f"line {lineno}: empty key")
        # Keys go through the same validation as values: `[a]: b` and `yes: a`
        # are a list and a boolean to YAML, not the strings they look like.
        key = _scalar(key, lineno, "key")
        if key in out:
            raise FrontmatterError(f"line {lineno}: duplicate key {key!r}")

        value = value.strip(" ")
        out[key] = _scalar(value, lineno, repr(key)) if value else None
        current_key = key
        list_indent = None

    return out, body
