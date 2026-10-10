#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical checks for a hand-written XRD schema.

Usage:
    python3 check_xrd_schema.py apis/*/definition.yaml
    python3 check_xrd_schema.py --min-corpus 3 apis/tiny/definition.yaml
    python3 check_xrd_schema.py --exceptions xrd-schema-exceptions.yaml apis/*/definition.yaml
    python3 check_xrd_schema.py --report-only apis/*/definition.yaml

Collisions, allowlist casing, group stutter, enum casing, missing descriptions,
unbounded lists and printer columns Crossplane already appends are all greppable
out of the YAML, before any cluster is involved. Everything this reports is
cheap to fix before the first version ships and impossible to fix afterwards,
because two XRD versions are two views of one stored object.

One trap sits underneath all of it: a check whose corpus is empty reports every
schema clean. The corpus is asserted before the verdict is trusted, and
extraction failure exits with a different code than a finding.

Exit codes, per the repo convention:

    0   clean
    10  validation failure -- at least one finding
    2   not found / extraction broken -- no files matched, PyYAML missing, or a
        corpus too small to have been extracted correctly. NOT a clean pass.

Casing is checked on two surfaces with different rules:

  * A FIELD is lowerCamel with the initialism title-cased, never canonicalised:
    vpcId, projectId, bucketArn, cacheTtlSeconds. This is not the Kubernetes
    core convention (containerID, imageID) and deliberately so: across the
    Crossplane resources a user sees beside an XR the field surface is
    title-case throughout, and `vpcID` next to `vpcId` is one concept with two
    spellings.

  * A KIND carries the initialism in full: VPC, DNSRecord, OIDCProvider,
    HTTPLoadBalancer. The Kind is the GVK and spec.names.kind, so unlike a
    field it cannot be renamed after release without making every stored
    object unreadable. It is the one name worth getting right up front.

The ACRONYMS allowlist therefore applies to the KIND only. Fields are checked
registry-free: under the field convention no word is ever all-caps, so any
all-caps run of two or more letters is a defect without needing a table, and a
token missing from the table is a missed defect rather than a false alarm.

What this reports as REVIEW rather than FAIL, because the call is semantic:

  * Group stutter. `artifactoryRepositoryName` restates the object's own
    identity and wants to be `name`; `gatewayName` on a Route names a DIFFERENT
    object that carries the group's word, and renaming it to `name` is worse.
    Both shapes are prefix-anchored matches on the group.
  * Booleans, and strings with no enum, pattern, maxLength or format.

Some findings are not yours to fix. Enum values that mirror an upstream API
verbatim (`aurora-postgresql`, `udp`) are not yours to rename when consumers
pass them through unchanged, and an API that has already shipped (a frozen or
brownfield API) cannot gain a description, a list type or a bound without a new
version. Record each such finding in an exceptions file, under its rule class,
with a reason:

    enumCasing:
      - field: apis/db/definition.yaml[*].spec.parameters.engine
        reason: AWS RDS engine names, passed through to the provider verbatim
    maxItems:
      - field: apis/network/definition.yaml[v1alpha1].status.subnetIds
        reason: frozen API, shipped without a bound

The rule classes and what `field` names for each:

    enumCasing, description, listType, maxItems, lowerCamel, fieldCasing
        the field path, scoped as the finding prints it:
        apis/db/definition.yaml[v1alpha1].spec.parameters.engine
    printerColumn   the column, scoped the same way: <file>[v1alpha1].READY
    kindAcronym     the Kind, scoped to its file only: <file>[*].HttpLoadbalancer
    collision       the spellings as printed (ProjectId / projectID). A
                    collision spans the corpus, so naming a file or version
                    is an input error.

The file is the path the finding prints, relative to the working directory.
Either part may be `*`: `<file>[*].` is every version of one XRD, `*[v1].` is
v1 of every XRD, and `*[*].` says on purpose that the entry is project-wide.
When several entries match a finding, the most specific one gives the reason.

A bare entry (spec.parameters.engine, with no `<file>[<version>].`) is the
older form. It still applies everywhere, so existing files keep working, but
when it excepts findings in more than one XRD or version it is reported for
REVIEW with the places it reached: an exception written for one frozen version
should not hide the same defect where it can still be fixed.

`uniqueItems` has no exception: the API server rejects the whole CRD.

The file is read from --exceptions, or from ./xrd-schema-exceptions.yaml when it
exists. Excepted findings print as EXCEPTED with their reason and do not fail
the run. An entry without a reason, under an unknown rule class, or with a scope
its rule cannot take is an input error (exit 2). An entry that no longer
matches a finding, or only matches findings a more specific entry already
covers, is reported for REVIEW, so stale exceptions surface.

--report-only prints the same report and exits 0 even with findings: use it to
read a frozen API's state, not as a gate. Extraction and input errors still
exit 2.

What it does not look at all, and why it does not try:

  * Kind stutter. `repositoryClass` is a good name and `repositoryName` is not,
    and the difference is semantic. A check that fires on both pushes someone to
    break the good one.
  * Which fields are identity fields needing `self == oldSelf`.
  * Whether a `pattern` matches what the backend actually enforces.

Those stay review judgements. See `charter/xrd-design.md`.
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import re
import sys

EXIT_CLEAN = 0
EXIT_FINDINGS = 10  # validation failure
EXIT_NO_CORPUS = 2  # not found

# ---------------------------------------------------------------------------
# KIND casing only. A Kind carries its initialism in full (VPC, DNSRecord,
# OIDCProvider), and it is the one name that cannot be renamed after release.
# Fields are NOT checked against this table -- the field surface is title-case
# (vpcId, bucketArn) and is checked registry-free below.
#
# ALLOWLIST, not a registry. A gap here is a missed defect, never a false
# alarm -- that inversion is the whole reason this shape works. A registry of
# canonical initialisms, used the other way round to decide what casing is
# wrong, fires on every name it does not know, so nearly every hit is a gap in
# the registry rather than a defect, and the check gets switched off.
#
# Every entry carries the expansion it stands for; an entry nobody can expand
# does not belong. Trim this to the acronyms your API actually uses, and add to
# it only with the expansion written down.
# ---------------------------------------------------------------------------
ACRONYMS = {
    "Api": "API",     # Application Programming Interface
    "Acl": "ACL",     # Access Control List
    "Arn": "ARN",     # Amazon Resource Name
    "Ca": "CA",       # Certificate Authority
    "Cidr": "CIDR",   # Classless Inter-Domain Routing
    "Cpu": "CPU",     # Central Processing Unit
    "Csi": "CSI",     # Container Storage Interface
    "Db": "DB",       # Database
    "Dns": "DNS",     # Domain Name System
    "Fqdn": "FQDN",   # Fully Qualified Domain Name
    "Http": "HTTP",   # HyperText Transfer Protocol
    "Https": "HTTPS", # HyperText Transfer Protocol Secure
    "Id": "ID",       # Identifier
    "Ip": "IP",       # Internet Protocol
    "Jwt": "JWT",     # JSON Web Token
    "Oidc": "OIDC",   # OpenID Connect
    "Os": "OS",       # Operating System
    "Ssh": "SSH",     # Secure Shell
    "Tls": "TLS",     # Transport Layer Security
    "Ttl": "TTL",     # Time To Live
    "Uri": "URI",     # Uniform Resource Identifier
    "Url": "URL",     # Uniform Resource Locator
    "Uuid": "UUID",   # Universally Unique Identifier
}

# Enum values that are proper nouns with established casing, where CamelCasing
# produces something wrong (Npm, Pypi). Each one is an exception you are
# choosing; keep the list short and write the reason beside the field.
ENUM_PROPER_NOUNS = {"npm", "PyPI", "NuGet"}

# Crossplane appends these to every XR. Defining one yourself prints it twice.
CROSSPLANE_COLUMNS = {"SYNCED", "READY", "COMPOSITION", "COMPOSITIONREVISION", "AGE"}

# Below this, extraction is broken -- not a clean pass. Override with
# --min-corpus when an API really is this small, so the small corpus is an
# assertion someone made rather than a silence nobody noticed.
DEFAULT_MIN_CORPUS = 5

XRD_KINDS = ("CompositeResourceDefinition", "CustomResourceDefinition")

DEFAULT_EXCEPTIONS = "xrd-schema-exceptions.yaml"

# Rule classes a finding can be excepted under, keyed as in the exceptions
# file. Every FAIL carries one of these or "uniqueItems", which is never
# excepted: the API server rejects the whole CRD, so no reason makes it work.
EXCEPTABLE_RULES = (
    "enumCasing",
    "description",
    "listType",
    "maxItems",
    "lowerCamel",
    "fieldCasing",
    "kindAcronym",
    "printerColumn",
    "collision",
)
NEVER_EXCEPTED = {
    "uniqueItems": "the API server rejects the whole CRD; use x-kubernetes-list-type: set",
}


class ExceptionsError(Exception):
    """The exceptions file cannot be used as written."""


def _yaml():
    """PyYAML, imported on first use so that `--help` works without it."""
    import yaml
    return yaml


# `<file>[<version>].<key>`, the form a finding prints. The version must be
# non-empty, which is what tells a qualified entry from a bare field path that
# goes through a list: `spec.rules[].port` has `[]`, never `[v1]`.
QUALIFIED = re.compile(r"^(?P<file>[^\[\]]+)\[(?P<version>[^\[\]]+)\]\.(?P<key>.+)$")


class Entry(collections.namedtuple("Entry", "field file version key reason")):
    """One exception. `file` and `version` are None for a bare (legacy) entry,
    which applies everywhere, and `*` where the entry says any."""

    @property
    def specificity(self):
        """Higher wins when several entries match one finding."""
        if self.file is None:
            return 0
        return 1 + 2 * (self.file != "*") + (self.version != "*")


def split_where(where):
    """`<file>[<version>].spec.x` -> (file, version, `spec.x`)."""
    m = QUALIFIED.match(where)
    if not m:
        return None, None, where
    return m.group("file"), m.group("version"), m.group("key")


def same_file(a, b):
    """`./apis/x.yaml`, `apis/x.yaml` and its absolute path are one file."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def format_place(place):
    file, version = place
    if file is None:
        return "the whole corpus"
    return file if version is None else f"{file}[{version}]"


def parse_entry(path, rule, i, field, reason):
    """Split `field` into its scope and key, rejecting scopes the rule cannot take."""
    m = QUALIFIED.match(field)
    if not m:
        return Entry(field, None, None, field, reason)
    file, version, key = m.group("file"), m.group("version"), m.group("key")
    if rule == "kindAcronym" and version != "*":
        raise ExceptionsError(
            f"{path}: {rule}[{i}] ({field}) names a version, but a Kind spans every "
            f"version -- write {file}[*].{key}"
        )
    if rule == "collision" and (file, version) != ("*", "*"):
        raise ExceptionsError(
            f"{path}: {rule}[{i}] ({field}) names a file or version, but a collision "
            f"spans the whole corpus -- write the spellings alone: {key}"
        )
    return Entry(field, file, version, key, reason)


def entry_matches(entry, place, key):
    """Whether `entry` covers a finding keyed `key` at `place` (file, version)."""
    if entry.key != key:
        return False
    if entry.file is None:
        return True
    file, version = place
    if entry.file != "*" and (file is None or not same_file(entry.file, file)):
        return False
    if entry.version != "*" and entry.version != version:
        return False
    return True


def load_exceptions(path):
    """Return {rule: [Entry]} for the exceptions in `path`."""
    with open(path, encoding="utf-8") as fh:
        doc = _yaml().safe_load(fh) or {}
    if not isinstance(doc, dict):
        raise ExceptionsError(
            f"{path}: expected a mapping of rule class to a list of {{field, reason}}"
        )
    out = {}
    for rule, entries in doc.items():
        if rule in NEVER_EXCEPTED:
            raise ExceptionsError(
                f"{path}: {rule} cannot be excepted -- {NEVER_EXCEPTED[rule]}"
            )
        if rule not in EXCEPTABLE_RULES:
            raise ExceptionsError(
                f"{path}: unknown rule class {rule!r} -- use one of "
                + ", ".join(EXCEPTABLE_RULES)
            )
        entries = entries or []
        if not isinstance(entries, list):
            raise ExceptionsError(f"{path}: {rule} must be a list")
        rule_out = {}
        for i, e in enumerate(entries):
            field = e.get("field") if isinstance(e, dict) else None
            reason = e.get("reason") if isinstance(e, dict) else None
            if not isinstance(field, str) or not field.strip():
                raise ExceptionsError(f"{path}: {rule}[{i}] has no field")
            if not isinstance(reason, str) or not reason.strip():
                raise ExceptionsError(
                    f"{path}: {rule}[{i}] ({field}) has no reason -- an exception "
                    "nobody can explain is a defect nobody fixed"
                )
            field = field.strip()
            # A repeated field keeps its last reason, as it always has.
            rule_out[field] = parse_entry(path, rule, i, field, reason.strip())
        out[rule] = list(rule_out.values())
    return out


def split_words(s):
    """Split a camelCase/PascalCase identifier at case-transition boundaries.

    A boundary falls before index i when s[i] is upper and s[i-1] is not (the
    ordinary hump: fooBar -> foo, Bar), or when s[i] and s[i-1] are both upper
    and s[i+1] is lower (the acronym run: HTTPServer -> HTTP, Server). Digits
    never start a word, so Ipv4 stays one word.

    This boundary test is the point: a substring replace reaches inside longer
    words and rewrites apiep (from api_ep) to APIep.
    """
    if not s:
        return []
    words, start, n = [], 0, len(s)
    for i in range(1, n):
        prev_upper, cur_upper = s[i - 1].isupper(), s[i].isupper()
        if not cur_upper:
            continue
        if not prev_upper:
            words.append(s[start:i])
            start = i
            continue
        if i + 1 < n and not s[i + 1].isupper() and s[i + 1].isalnum():
            words.append(s[start:i])
            start = i
    words.append(s[start:])
    return words


def kind_acronym_violations(kind):
    """Title-cased initialisms in a PascalCase Kind: Http -> HTTP.

    A Kind carries its initialism in full (VPC, OIDCProvider, DNSRecord,
    HTTPLoadBalancer), and it is the GVK and spec.names.kind, so it is the one
    name a later release cannot fix. Checked against the allowlist, where a gap
    is a missed defect and never a false alarm.

    Only the token itself is decidable. `HttpLoadbalancer` also has a missing
    word boundary inside `Loadbalancer`, which no table can see.
    """
    out = []
    for w in split_words(kind):
        if w in ACRONYMS:
            out.append((w, ACRONYMS[w]))
    return out


def field_casing_violations(name):
    """All-caps runs in a lowerCamel field name: vpcID -> vpcId.

    The field surface is title-case throughout (vpcId, bucketArn,
    cacheTtlSeconds), so no word in a correct field name is ever all-caps. That makes this registry-free: the check needs no
    table and cannot false-alarm on an ordinary English word or on an acronym
    nobody wrote down.

    A canonicalised field is not a style preference. `vpcID` beside the `vpcId`
    on every resource a user sees next to this XR is one concept with two
    spellings -- the defect this exists to catch.

    Word 0 is skipped: it is lowercase by the lowerCamel convention, and a
    field that does not start lowercase is reported separately. Single letters
    are skipped too, so the `A` in `enableResourceNameDnsARecordOnLaunch` (a
    DNS A record) is left alone.
    """
    out = []
    for i, w in enumerate(split_words(name)):
        if i == 0 or len(w) < 2 or not w.isupper():
            continue
        # Alphabetic only. `S3` and `V3` are already their own title-case form,
        # so flagging them prints a "fix" identical to the input.
        if not w.isalpha():
            continue
        out.append((w, w[0] + w[1:].lower()))
    return out


def walk(node, path, names, findings, review, in_status):
    """Collect every property name and check each node's own schema."""
    if not isinstance(node, dict):
        return

    props = node.get("properties")
    if isinstance(props, dict):
        for k, v in props.items():
            child = f"{path}.{k}"
            names.append((k, child))

            if isinstance(v, dict):
                file, version, key = split_where(child)
                place = (file, version)
                if not v.get("description"):
                    findings.append(("description", place, key, f"{child}: no description"))

                t = v.get("type")
                if t == "string" and not any(
                    x in v for x in ("enum", "pattern", "maxLength", "format")
                ):
                    review.append(
                        f"{child}: bare `type: string` -- no enum, pattern, maxLength or format"
                    )
                if t == "boolean" and not in_status:
                    review.append(
                        f"{child}: boolean -- a two-value enum that can never gain a third"
                    )
                if t == "array":
                    if "x-kubernetes-list-type" not in v:
                        findings.append((
                            "listType",
                            place,
                            key,
                            f"{child}: array with no x-kubernetes-list-type (atomic by default: "
                            "duplicates accepted, server-side apply clobbers)",
                        ))
                    if "maxItems" not in v:
                        findings.append((
                            "maxItems",
                            place,
                            key,
                            f"{child}: array with no maxItems (CEL cost is budgeted against "
                            "the declared maximum)",
                        ))
                # Not style. The API server refuses to create the CRD at all:
                # "uniqueItems cannot be set to true since the runtime
                # complexity becomes quadratic" (apiextensions-apiserver
                # validation.go). It is the obvious way to write "duplicates
                # are rejected", and the correct one is list-type: set.
                if v.get("uniqueItems") is True:
                    findings.append((
                        "uniqueItems",
                        place,
                        key,
                        f"{child}: uniqueItems: true is forbidden in a CRD schema -- the API "
                        "server rejects the whole CRD (\"runtime complexity becomes "
                        "quadratic\"). Use x-kubernetes-list-type: set",
                    ))
                for ev in v.get("enum", []) or []:
                    if not isinstance(ev, str) or ev in ENUM_PROPER_NOUNS:
                        continue
                    if not ev[:1].isupper():
                        findings.append((
                            "enumCasing",
                            place,
                            key,
                            f"{child}: enum value {ev!r} is not CamelCase with an initial capital",
                        ))

            walk(v, child, names, findings, review, in_status)

    items = node.get("items")
    if isinstance(items, dict):
        walk(items, f"{path}[]", names, findings, review, in_status)


def check(path):
    """Return (names, findings, review, kind_count) for one YAML file.

    Each finding is a (rule, place, key, text) tuple: the rule class, the
    (file, version) it was found in, the key an exception names, and the line
    the report prints. A Kind's place has version None: it spans every version.
    """
    with open(path, encoding="utf-8") as fh:
        docs = [d for d in _yaml().safe_load_all(fh) if isinstance(d, dict)]

    names, findings, review = [], [], []
    kinds = 0

    for d in docs:
        if d.get("kind") not in XRD_KINDS:
            continue
        spec = d.get("spec") or {}
        kind = ((spec.get("names") or {}).get("kind")) or ""
        group = spec.get("group") or ""

        # Names from THIS document only. The stutter check below compares them
        # against this document's group, so a file holding two XRDs must not
        # check the first one's fields against the second one's group --
        # `repositoryClass` under group `artifactory.example.com` is a good
        # name, and reading it beside a second XRD in group
        # `repository.example.com` reported it as stutter.
        doc_names = []

        if kind:
            kinds += 1
            for w, want in kind_acronym_violations(kind):
                findings.append((
                    "kindAcronym",
                    (path, None),
                    kind,
                    f"{path}: Kind {kind!r} carries mis-cased acronym {w!r} (want {want!r}). "
                    "A Kind is the GVK and spec.names.kind -- renaming it stops the CRD "
                    "serving the old name and every stored object becomes unreadable. "
                    "This is not a rename you can make later.",
                ))

        for v in spec.get("versions") or []:
            vn = v.get("name")
            schema = ((v.get("schema") or {}).get("openAPIV3Schema")) or {}
            root = schema.get("properties") or {}
            for section in ("spec", "status"):
                if section in root:
                    walk(
                        root[section],
                        f"{path}[{vn}].{section}",
                        doc_names,
                        findings,
                        review,
                        in_status=(section == "status"),
                    )

            cols = {
                c.get("name", "").upper()
                for c in (v.get("additionalPrinterColumns") or [])
            }
            for dup in sorted(cols & CROSSPLANE_COLUMNS):
                findings.append((
                    "printerColumn",
                    (path, vn),
                    dup,
                    f"{path}[{vn}]: printer column {dup} is already appended by Crossplane "
                    "-- it will print twice",
                ))

        # Group stutter, checked against the GROUP's first label only,
        # prefix-anchored, and REVIEW rather than FAIL. It cannot tell apart
        # two shapes that look identical:
        #
        #   artifactoryRepositoryName -- restates this object's own identity.
        #                                Real stutter; it wants to be `name`.
        #   gatewayName               -- names a DIFFERENT object that happens
        #                                to carry the group's word. Renaming it
        #                                to `name` is actively worse, because
        #                                `name` no longer says whose.
        #   gatewayTimeoutSeconds     -- a compound term (HTTP 504 Gateway
        #                                Timeout) that begins with the word.
        #
        # The difference is semantic, which is the same reason kind stutter is
        # left to review. Both shapes were produced by an agent on one API.
        stem = group.split(".")[0].lower()
        for n, where in doc_names:
            if stem and n.lower() != stem and n.lower().startswith(stem):
                review.append(
                    f"{where}: field name {n!r} starts with the group {stem!r} -- "
                    f"it reads as {stem}.{kind}.{n}. Stutter if it restates this "
                    f"object's own identity; fine if it names a different object"
                )

        names.extend(doc_names)

    return names, findings, review, kinds


def run(patterns, min_corpus=DEFAULT_MIN_CORPUS, out=None, exceptions=None,
        report_only=False):
    """Check every file matching `patterns`. Returns an exit code.

    `exceptions` is a path to an exceptions file. None means use
    DEFAULT_EXCEPTIONS from the current directory when it exists.
    `report_only` exits clean despite findings; errors still exit 2.
    """
    out = out or sys.stdout
    try:
        yaml = _yaml()
    except ImportError:
        print("ERROR: PyYAML is not installed (pip install pyyaml), so no schema could be "
              "read: an extraction failure, not a clean pass.", file=sys.stderr)
        return EXIT_NO_CORPUS
    if exceptions is None and os.path.exists(DEFAULT_EXCEPTIONS):
        exceptions = DEFAULT_EXCEPTIONS
    excepted_rules = {}
    if exceptions:
        try:
            excepted_rules = load_exceptions(exceptions)
        except (OSError, yaml.YAMLError, ExceptionsError) as e:
            print(f"EXCEPTIONS ERROR: {e}", file=out)
            return EXIT_NO_CORPUS
    paths = []
    for a in patterns:
        paths.extend(sorted(glob.glob(a)))
    if not paths:
        print(
            "CORPUS ERROR: no files matched -- extraction is broken, not a clean pass",
            file=out,
        )
        return EXIT_NO_CORPUS

    all_names, all_findings, all_review, kinds = [], [], [], 0
    for p in paths:
        names, findings, review, k = check(p)
        all_names.extend(names)
        all_findings.extend(findings)
        all_review.extend(review)
        kinds += k

    # A check whose corpus is empty reports every schema clean. Assert the
    # corpus before trusting the verdict.
    if len(all_names) < min_corpus or kinds == 0:
        print(
            f"CORPUS ERROR: {len(all_names)} field names, {kinds} kinds across "
            f"{len(paths)} file(s) -- extraction is broken, not a clean pass. "
            f"If the API really is this small, pass --min-corpus.",
            file=out,
        )
        return EXIT_NO_CORPUS

    # Naming, checked two ways. Neither subsumes the other.
    #
    # 1. Collision: one concept spelled two ways (projectId / ProjectID).
    #    Registry-free, so no false positive from an ordinary English word.
    #    Blind to an acronym spelled two ways across names that never collide.
    seen = {}
    for n, _ in all_names:
        seen.setdefault(n.lower(), set()).add(n)
    for _, spellings in sorted(seen.items()):
        if len(spellings) > 1:
            both = " / ".join(sorted(spellings))
            all_findings.append((
                "collision", (None, None), both, f"one concept, two spellings: {both}"
            ))

    # 2. Field casing: an all-caps initialism, which the field surface never
    #    uses. Registry-free, and invisible to (1) when the two spellings live
    #    on different sides of the composition rather than in one schema.
    for n, where in all_names:
        file, version, key = split_where(where)
        if n[:1].isupper():
            all_findings.append((
                "lowerCamel",
                (file, version),
                key,
                f"{where}: field name {n!r} is not lowerCamel -- it must start lowercase",
            ))
        for w, want in field_casing_violations(n):
            # Detection is registry-free; the table only picks the advice. A
            # token nobody can expand is an invented abbreviation, and
            # title-casing it (adminsSG -> adminsSg) answers the casing
            # question while leaving the worse problem in place.
            if w in set(ACRONYMS.values()):
                fix = (
                    f"the field surface is title-case, so write {want!r}. Everything "
                    f"a user sees beside this XR spells it that way"
                )
            else:
                fix = (
                    f"the field surface is title-case, so this is at best {want!r} -- but "
                    f"{w!r} is not an acronym with a written-down expansion, so expand it "
                    f"into a word instead and the casing question disappears"
                )
            all_findings.append((
                "fieldCasing",
                (file, version),
                key,
                f"{where}: field name {n!r} canonicalises {w!r} -- {fix}",
            ))

    # Each finding takes the most specific entry that matches it, so a scoped
    # entry beside a bare one carries its own reason. Per entry we record where
    # it was applied, and whether it matched at all, so stale and shadowed
    # entries surface one by one.
    excepted, kept = [], []
    applied = {}   # (rule, field) -> set of places the entry excepted
    matched = set()  # (rule, field) of every entry that matched some finding
    for rule, place, key, text in all_findings:
        hits = [e for e in excepted_rules.get(rule, []) if entry_matches(e, place, key)]
        if not hits:
            kept.append(text)
            continue
        matched.update((rule, e.field) for e in hits)
        best = max(hits, key=lambda e: e.specificity)
        applied.setdefault((rule, best.field), set()).add(place)
        excepted.append(f"{text} -- {best.reason}")
    all_findings = kept
    for rule in EXCEPTABLE_RULES:
        for e in sorted(excepted_rules.get(rule, []), key=lambda e: e.field):
            places = applied.get((rule, e.field))
            if (rule, e.field) not in matched:
                all_review.append(
                    f"{exceptions}: {rule} exception for {e.field!r} matches no finding -- "
                    + ("remove it, or fix the field path" if e.file is None
                       else "remove it, or fix the file, version or field path")
                )
            elif not places:
                all_review.append(
                    f"{exceptions}: {rule} exception for {e.field!r} is shadowed -- every "
                    "finding it matches is excepted by a more specific entry. Remove it"
                )
            elif e.file is None and len(places) > 1:
                # A bare entry still applies everywhere, so files written before
                # entries took a scope keep working. But a waiver for one frozen
                # version also hides the same finding where it should be fixed.
                where = ", ".join(
                    format_place(p)
                    for p in sorted(places, key=lambda p: (p[0] or "", p[1] or ""))
                )
                if rule == "kindAcronym":
                    scoped, wide = f"<file>[*].{e.key}", f"*[*].{e.key}"
                else:
                    scoped, wide = f"<file>[<version>].{e.key}", f"*[*].{e.key}"
                all_review.append(
                    f"{exceptions}: {rule} exception for {e.field!r} has no file or "
                    f"version, so it excepts {len(places)} places: {where} -- scope it as "
                    f"{scoped}, or write {wide} if it is meant for the whole project"
                )

    for f in sorted(set(all_findings)):
        print("FAIL:   " + f, file=out)
    for f in sorted(set(excepted)):
        print("EXCEPTED: " + f, file=out)
    for f in sorted(set(all_review)):
        print("REVIEW: " + f, file=out)
    print(
        f"\ncorpus: {len(all_names)} field names, {kinds} kind(s), {len(paths)} file(s); "
        f"{len(set(all_findings))} failure(s), {len(set(all_review))} to review"
        + (f", {len(set(excepted))} excepted" if excepted else "")
        + ("; report only, findings do not fail the run" if report_only else ""),
        file=out,
    )
    if report_only:
        return EXIT_CLEAN
    return EXIT_FINDINGS if all_findings else EXIT_CLEAN


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Mechanical checks for a hand-written XRD schema.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exceptions file, one list per rule class:\n"
            "  enumCasing:\n"
            "    - field: apis/db/definition.yaml[v1alpha1].spec.engine\n"
            "      reason: AWS RDS engine names, passed through verbatim\n"
            "\n"
            "A field is scoped as the finding prints it, <file>[<version>].<path>, and\n"
            "either part may be *. printerColumn takes <file>[<version>].<COLUMN>,\n"
            "kindAcronym <file>[*].<Kind>, collision the spellings alone. A bare path\n"
            "still applies to every XRD and version, and is reported for REVIEW when it\n"
            "excepts findings in more than one; write *[*].<path> to mean that."
        ),
    )
    ap.add_argument(
        "paths",
        nargs="*",
        default=["apis/*/definition.yaml"],
        metavar="PATH",
        help="XRD files or globs (default: apis/*/definition.yaml)",
    )
    ap.add_argument(
        "--min-corpus",
        type=int,
        default=DEFAULT_MIN_CORPUS,
        metavar="N",
        help=(
            f"fewest field names that count as a real extraction "
            f"(default: {DEFAULT_MIN_CORPUS}). Below it the run is an error, not a pass."
        ),
    )
    ap.add_argument(
        "--exceptions",
        metavar="FILE",
        help=(
            f"exceptions by rule class, each with a reason (default: ./{DEFAULT_EXCEPTIONS} "
            "when it exists); format below"
        ),
    )
    ap.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "print every finding but exit 0 despite them, e.g. to read a frozen API; "
            "extraction and input errors still exit 2"
        ),
    )
    args = ap.parse_args(argv)
    return run(
        args.paths,
        min_corpus=args.min_corpus,
        exceptions=args.exceptions,
        report_only=args.report_only,
    )


if __name__ == "__main__":
    sys.exit(main())
