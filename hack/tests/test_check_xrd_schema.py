# SPDX-License-Identifier: Apache-2.0
"""Tests for check_xrd_schema.py.

Three properties are verified rather than trusted, because a naming checker can
be wrong in ways that look exactly like compliance:

1. `good.yaml` exits clean. A suite where everything fails proves nothing -- it
   is equally consistent with a checker that rejects every schema.
2. Casing is checked on two surfaces with OPPOSITE rules. A Kind carries the
   initialism in full (`HTTPLoadBalancer`); a field never does (`vpcId`,
   `cacheTtlSeconds`). `originPoolId` must pass while `backendPoolID` fails.
3. Extraction failure exits with its own code, distinguishable at the call site
   from both a clean pass and a finding.
"""

from __future__ import annotations

import contextlib
import copy
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "author-configuration-package" / "scripts"
sys.path.insert(0, str(SCRIPTS))
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "check_xrd_schema"

try:
    import yaml  # noqa: F401  -- check_xrd_schema needs PyYAML
    import check_xrd_schema as c
except ImportError:
    c = None


def run(paths, min_corpus=None, exceptions=None):
    """Run the checker over `paths`, returning (exit_code, output)."""
    out = io.StringIO()
    if min_corpus is None:
        min_corpus = c.DEFAULT_MIN_CORPUS
    code = c.run(
        [str(p) for p in paths],
        min_corpus=min_corpus,
        out=out,
        exceptions=str(exceptions) if exceptions else None,
    )
    return code, out.getvalue()


@unittest.skipIf(c is None, "PyYAML is not installed; check_xrd_schema.py needs it")
class CheckXrdSchemaTest(unittest.TestCase):
    """Ported from the pytest suite that shipped with the internal plugin."""

    def tmp(self) -> Path:
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d




    # ---------------------------------------------------------------------------
    # Property 1: the control passes
    # ---------------------------------------------------------------------------

    def test_good_schema_is_clean(self):
        """The valid control must pass, or every other assertion here is vacuous."""
        good_xrd = FIXTURES / 'good.yaml'
        code, output = run([good_xrd])
        assert code == c.EXIT_CLEAN, output
        assert "FAIL:" not in output
        assert "REVIEW:" not in output

    def test_good_schema_corpus_is_real(self):
        """A clean verdict is only meaningful if something was actually extracted."""
        good_xrd = FIXTURES / 'good.yaml'
        _code, output = run([good_xrd])
        assert "corpus: 12 field names, 1 kind(s), 1 file(s)" in output

    # ---------------------------------------------------------------------------
    # Property 2: one planted defect per rule, each one caught
    # ---------------------------------------------------------------------------

    def test_bad_schema_is_rejected(self):
        bad_xrd = FIXTURES / 'bad.yaml'
        code, _output = run([bad_xrd])
        assert code == c.EXIT_FINDINGS

    def test_collision_check_catches_one_concept_two_spellings(self):
        """projectID beside ProjectId -- registry-free, so no false positive."""
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "one concept, two spellings: ProjectId / projectID" in output

    def test_field_canonicalised_initialism_is_caught(self):
        """vpcID is the defect, not vpcId. The field surface is title-case."""
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "field name 'projectID' canonicalises 'ID'" in output
        assert "write 'Id'" in output

    def test_field_not_lowercamel_is_caught(self):
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "field name 'ProjectId' is not lowerCamel" in output

    def test_invented_abbreviation_is_told_to_expand_not_recase(self):
        """adminsSG -> adminsSg answers the casing question and keeps the worse one.

        Detection stays registry-free; the table only picks the advice.
        """
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "'SG' is not an acronym with a written-down expansion" in output
        assert "expand it into a word instead" in output

    def test_group_stutter_is_review_not_fail(self):
        """Stutter is prefix-anchored, and the prefix does not tell you the shape.

        `artifactoryRepositoryName` restates the object's own identity and is real
        stutter. `gatewayName` on a Route names a different object. Both are
        prefix matches, so the call is semantic and belongs in REVIEW.
        """
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        line = "field name 'artifactoryRepositoryName' starts with the group 'artifactory'"
        hits = [ln for ln in output.splitlines() if line in ln]
        assert len(hits) == 1, output
        assert hits[0].startswith("REVIEW:")

    def test_missing_description_is_caught(self):
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "spec.artifactoryRepositoryName: no description" in output

    def test_lowercase_enum_values_are_caught(self):
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "enum value 'maven' is not CamelCase with an initial capital" in output
        assert "enum value 'tls12' is not CamelCase with an initial capital" in output

    def test_proper_noun_enum_value_is_not_flagged(self):
        """npm is a proper noun with established casing; Npm would be wrong."""
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "enum value 'npm'" not in output

    def test_unbounded_list_is_caught(self):
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "array with no x-kubernetes-list-type" in output
        assert "array with no maxItems" in output

    def test_unique_items_is_caught(self):
        """Not style: the API server refuses to create a CRD that carries it.

        An agent reached for `uniqueItems: true` to express the vendor's
        "duplicates are rejected" and produced a CRD the API server rejects
        outright. The correct construct is x-kubernetes-list-type: set.
        """
        trial_xrd = FIXTURES / 'trial-gateway.yaml'
        code, output = run([trial_xrd])
        assert code == c.EXIT_FINDINGS
        assert "uniqueItems: true is forbidden in a CRD schema" in output
        assert any(
            "uniqueItems" in ln for ln in output.splitlines() if ln.startswith("FAIL:")
        )

    def test_duplicate_printer_column_is_caught(self):
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        assert "printer column READY is already appended by Crossplane" in output

    def test_booleans_and_bare_strings_are_review_not_fail(self):
        """A check that fails every boolean gets disabled. The call is a judgement."""
        bad_xrd = FIXTURES / 'bad.yaml'
        _code, output = run([bad_xrd])
        review = [ln for ln in output.splitlines() if ln.startswith("REVIEW:")]
        assert any("xrayIndex: boolean" in ln for ln in review)
        assert any("bare `type: string`" in ln for ln in review)
        assert not any("xrayIndex" in ln for ln in output.splitlines() if ln.startswith("FAIL:"))

    # ---------------------------------------------------------------------------
    # Property 3: the word boundary, and the Kind
    # ---------------------------------------------------------------------------

    def test_kind_acronym_is_caught(self):
        """A Kind is the GVK. This is the one name that cannot be renamed later."""
        kind_xrd = FIXTURES / 'kind.yaml'
        code, output = run([kind_xrd])
        assert code == c.EXIT_FINDINGS
        assert "Kind 'HttpLoadbalancer' carries mis-cased acronym 'Http' (want 'HTTP')" in output

    def test_the_two_surfaces_do_not_leak_into_each_other(self):
        """The same file has a Kind that must canonicalise and fields that must not.

        `originPoolId` and `vmiId` are correct field names under the title-case
        rule, while `backendPoolID` is the defect. The allowlist applies to the
        Kind only.
        """
        kind_xrd = FIXTURES / 'kind.yaml'
        _code, output = run([kind_xrd])
        assert "backendPoolID" in output
        assert "originPoolId'" not in output
        assert "vmiId" not in output

    def test_word_boundary_spares_apiep(self):
        """apiepPort must NOT be flagged.

        A bare ReplaceAll(s, "Api", "API") would rewrite apiep (from api_ep) to
        APIep. The boundary test is end-of-word or a following uppercase letter.
        """
        kind_xrd = FIXTURES / 'kind.yaml'
        _code, output = run([kind_xrd])
        assert "apiepPort" not in output

    def test_kind_check_ignores_field_spellings(self):
        assert c.kind_acronym_violations("HttpLoadbalancer") == [("Http", "HTTP")]
        assert c.kind_acronym_violations("VPC") == []
        assert c.kind_acronym_violations("OIDCProvider") == []
        assert c.kind_acronym_violations("DNSRecord") == []

    def test_field_check_is_registry_free(self):
        """No table is consulted: any all-caps run of two or more is a defect."""
        assert c.field_casing_violations("vpcID") == [("ID", "Id")]
        assert c.field_casing_violations("vpcArnXYZ") == [("XYZ", "Xyz")]
        assert c.field_casing_violations("vpcId") == []
        assert c.field_casing_violations("cacheTtlSeconds") == []
        assert c.field_casing_violations("bucketArn") == []
        assert c.field_casing_violations("enableIpForwarding") == []
        assert c.field_casing_violations("primaryIpv4Address") == []
        assert c.field_casing_violations("enableResourceNameDnsARecordOnLaunch") == []

    def test_split_words_boundaries(self):
        assert c.split_words("apiepPort") == ["apiep", "Port"]
        assert c.split_words("projectId") == ["project", "Id"]
        assert c.split_words("HTTPServer") == ["HTTP", "Server"]
        assert c.split_words("primaryIpv4Address") == ["primary", "Ipv4", "Address"]
        assert c.split_words("") == []

    def test_leading_acronym_is_never_flagged(self):
        """Word 0 is lowercase by the lowerCamel convention: tlsConfig is correct."""
        assert c.field_casing_violations("tlsConfig") == []
        assert c.field_casing_violations("httpGet") == []
        assert c.field_casing_violations("urlPrefix") == []

    # ---------------------------------------------------------------------------
    # Property 4: the corpus assertion
    # ---------------------------------------------------------------------------

    def test_missing_file_is_an_error_not_a_pass(self):
        """Extraction failure must be distinguishable from a clean pass."""
        tmp_path = self.tmp()
        code, output = run([tmp_path / "nosuch.yaml"])
        assert code == c.EXIT_NO_CORPUS
        assert code != c.EXIT_CLEAN
        assert code != c.EXIT_FINDINGS
        assert "CORPUS ERROR" in output

    def test_empty_corpus_is_an_error_not_a_pass(self):
        """A file with no XRD in it extracts nothing, and nothing is not clean."""
        tmp_path = self.tmp()
        empty = tmp_path / "notanxrd.yaml"
        empty.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x\n")
        code, output = run([empty])
        assert code == c.EXIT_NO_CORPUS
        assert "CORPUS ERROR" in output

    def test_min_corpus_makes_a_small_api_an_explicit_choice(self):
        """A genuinely tiny API is allowed, but only by saying so."""
        fixtures_dir = FIXTURES
        tmp_path = self.tmp()
        tiny = tmp_path / "tiny.yaml"
        tiny.write_text(
            "apiVersion: apiextensions.crossplane.io/v2\n"
            "kind: CompositeResourceDefinition\n"
            "metadata:\n  name: pings.net.example.com\n"
            "spec:\n"
            "  group: net.example.com\n"
            "  names:\n    kind: Ping\n    plural: pings\n"
            "  versions:\n"
            "  - name: v1alpha1\n"
            "    schema:\n"
            "      openAPIV3Schema:\n"
            "        type: object\n"
            "        properties:\n"
            "          spec:\n"
            "            type: object\n"
            "            properties:\n"
            "              target:\n"
            "                type: string\n"
            "                description: Host to ping\n"
            "                maxLength: 253\n"
        )
        assert run([tiny])[0] == c.EXIT_NO_CORPUS
        assert run([tiny], min_corpus=1)[0] == c.EXIT_CLEAN

    # ---------------------------------------------------------------------------
    # Property 5: stutter is scoped to the document that declares the group
    # ---------------------------------------------------------------------------

    def test_group_stutter_does_not_leak_across_documents(self):
        """`repositoryClass` under group artifactory is a good name.

        Reading it in the same file as a second XRD in group `repository.example.com`
        must not report it as stutter -- a naming check that fires falsely gets
        switched off, which is the failure mode this whole file exists to avoid.
        """
        two_groups_xrd = FIXTURES / 'two-groups.yaml'
        code, output = run([two_groups_xrd])
        assert code == c.EXIT_CLEAN, output
        assert "repositoryClass" not in output
        assert "corpus: 5 field names, 2 kind(s), 1 file(s)" in output

    # ---------------------------------------------------------------------------
    # Cross-file behaviour
    # ---------------------------------------------------------------------------

    def test_collision_is_found_across_files(self):
        """The corpus is every file passed, so a collision spanning two files counts."""
        fixtures_dir = FIXTURES
        code, output = run([fixtures_dir / "good.yaml", fixtures_dir / "kind.yaml"])
        assert code == c.EXIT_FINDINGS
        assert "corpus: 19 field names, 2 kind(s), 2 file(s)" in output

    # ---------------------------------------------------------------------------
    # Property 6: real agent output, kept as a regression fixture
    # ---------------------------------------------------------------------------

    def test_trial_output_defects_are_all_caught(self):
        """Every defect below was produced by an agent working from a vendor spec
        with no design guidance, not planted by hand."""
        trial_xrd = FIXTURES / 'trial-gateway.yaml'
        code, output = run([trial_xrd])
        assert code == c.EXIT_FINDINGS
        for expected in [
            "enum value 'http' is not CamelCase with an initial capital",
            "enum value 'grpc' is not CamelCase with an initial capital",
            "printer column READY is already appended by Crossplane",
            "printer column AGE is already appended by Crossplane",
            "uniqueItems: true is forbidden in a CRD schema",
        ]:
            assert expected in output, expected

    def test_trial_output_spares_every_id_field(self):
        """apiId, routeId, resolvedUrl and cacheTtlSeconds are all CORRECT.

        An earlier draft of this check flagged all four and pushed an agent into
        writing apiID/routeID/resolvedURL/cacheTTLSeconds, which is the defect,
        not the fix. They must never appear as FAIL again.
        """
        trial_xrd = FIXTURES / 'trial-gateway.yaml'
        _code, output = run([trial_xrd])
        fails = [ln for ln in output.splitlines() if ln.startswith("FAIL:")]
        for correct in ("apiId", "routeId", "resolvedUrl", "cacheTtlSeconds",
                        "apiEndpointPort"):
            assert not any(correct in ln for ln in fails), correct

    def test_both_stutter_shapes_are_review(self):
        """gatewayName names another object; gatewayTimeoutSeconds is HTTP 504.

        Neither is a defect the check can assert, and both are prefix matches on
        the group, so both belong in REVIEW.
        """
        trial_xrd = FIXTURES / 'trial-gateway.yaml'
        _code, output = run([trial_xrd])
        fails = [ln for ln in output.splitlines() if ln.startswith("FAIL:")]
        reviews = [ln for ln in output.splitlines() if ln.startswith("REVIEW:")]
        assert any("gatewayName" in ln for ln in reviews)
        assert any("gatewayTimeoutSeconds" in ln for ln in reviews)
        assert not any("gatewayName" in ln or "gatewayTimeoutSeconds" in ln for ln in fails)

    # ---------------------------------------------------------------------------
    # Enum-casing exceptions: values that mirror an upstream API verbatim
    # ---------------------------------------------------------------------------

    def exceptions_file(self, body):
        f = self.tmp() / "xrd-schema-exceptions.yaml"
        f.write_text(body)
        return f

    def test_excepted_enum_prints_its_reason_and_other_findings_stay(self):
        exc = self.exceptions_file(
            "enumCasing:\n"
            "  - field: spec.packageType\n"
            "    reason: package manager names as the registry spells them\n"
        )
        code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert code == c.EXIT_FINDINGS
        assert "FAIL:   " not in "\n".join(
            ln for ln in output.splitlines() if "packageType: enum value" in ln
        )
        assert (
            "EXCEPTED: " in output
            and "spec.packageType: enum value 'maven'" in output
            and "-- package manager names as the registry spells them" in output
        )
        assert "FAIL:   " in output and "minVersion: enum value 'tls12'" in output

    def test_schema_whose_only_defects_are_excepted_exits_clean(self):
        d = self.tmp()
        xrd = d / "definition.yaml"
        xrd.write_text(
            (FIXTURES / "good.yaml").read_text().replace(
                "enum: [TLS12, TLS13]", "enum: [tls12, tls13]"
            )
        )
        exc = self.exceptions_file(
            "enumCasing:\n"
            "  - field: spec.tlsConfig.minVersion\n"
            "    reason: OpenSSL protocol names, passed through verbatim\n"
        )
        code, output = run([xrd])
        assert code == c.EXIT_FINDINGS, output
        code, output = run([xrd], exceptions=exc)
        assert code == c.EXIT_CLEAN, output
        assert "2 excepted" in output

    def test_exception_without_reason_is_an_input_error(self):
        exc = self.exceptions_file("enumCasing:\n  - field: spec.packageType\n")
        code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert code == c.EXIT_NO_CORPUS
        assert "EXCEPTIONS ERROR" in output and "has no reason" in output

    def test_stale_exception_is_reported_for_review(self):
        exc = self.exceptions_file(
            "enumCasing:\n"
            "  - field: spec.noSuchField\n"
            "    reason: left over from a rename\n"
        )
        _code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert any(
            ln.startswith("REVIEW:") and "'spec.noSuchField' matches no finding" in ln
            for ln in output.splitlines()
        ), output

    def test_default_exceptions_file_is_read_from_the_working_directory(self):
        exc = self.exceptions_file(
            "enumCasing:\n"
            "  - field: spec.packageType\n"
            "    reason: package manager names as the registry spells them\n"
        )
        cwd = os.getcwd()
        os.chdir(exc.parent)
        self.addCleanup(os.chdir, cwd)
        _code, output = run([FIXTURES / "bad.yaml"])
        assert "EXCEPTED: " in output and "spec.packageType" in output

    # ---------------------------------------------------------------------------
    # Exceptions by rule class, and --report-only: a frozen or brownfield API
    # ---------------------------------------------------------------------------

    def test_every_rule_class_can_be_excepted_by_its_key(self):
        """A frozen API's findings are permanent; each class takes its own key."""
        exc = self.exceptions_file(
            "lowerCamel:\n"
            "  - {field: spec.ProjectId, reason: frozen}\n"
            "maxItems:\n"
            "  - {field: spec.adminsSG, reason: frozen}\n"
            "listType:\n"
            "  - {field: spec.adminsSG, reason: frozen}\n"
            "fieldCasing:\n"
            "  - {field: spec.adminsSG, reason: frozen}\n"
            "  - {field: spec.projectID, reason: frozen}\n"
            "  - {field: spec.backendPoolID, reason: frozen}\n"
            "description:\n"
            "  - {field: spec.artifactoryRepositoryName, reason: frozen}\n"
            "enumCasing:\n"
            "  - {field: spec.packageType, reason: frozen}\n"
            "  - {field: spec.tlsParameters.minVersion, reason: frozen}\n"
            "printerColumn:\n"
            "  - {field: READY, reason: frozen}\n"
            "kindAcronym:\n"
            "  - {field: HttpLoadbalancer, reason: frozen}\n"
            "collision:\n"
            "  - {field: ProjectId / projectID, reason: frozen}\n"
        )
        code, output = run([FIXTURES / "bad.yaml", FIXTURES / "kind.yaml"], exceptions=exc)
        assert code == c.EXIT_CLEAN, output
        assert "FAIL:" not in output
        assert "0 failure(s)" in output and "12 excepted" in output
        assert "matches no finding" not in output

    def test_an_exception_covers_its_own_rule_class_only(self):
        """Excepting maxItems on a field must leave its listType finding failing."""
        exc = self.exceptions_file(
            "maxItems:\n  - {field: spec.adminsSG, reason: frozen API, shipped unbounded}\n"
        )
        code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert code == c.EXIT_FINDINGS
        lines = output.splitlines()
        assert any(ln.startswith("EXCEPTED: ") and "adminsSG: array with no maxItems" in ln
                   for ln in lines), output
        assert any(ln.startswith("FAIL:   ") and "adminsSG: array with no x-kubernetes-list-type"
                   in ln for ln in lines), output

    def test_stale_exception_in_any_class_is_reported(self):
        exc = self.exceptions_file(
            "description:\n  - {field: spec.noSuchField, reason: left over from a rename}\n"
        )
        _code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert any(
            ln.startswith("REVIEW:") and "description exception for 'spec.noSuchField'" in ln
            for ln in output.splitlines()
        ), output

    def test_unknown_rule_class_is_an_input_error(self):
        """A misspelt class would silently except nothing; name the valid ones."""
        exc = self.exceptions_file("maxitems:\n  - {field: spec.adminsSG, reason: frozen}\n")
        code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert code == c.EXIT_NO_CORPUS
        assert "unknown rule class 'maxitems'" in output and "maxItems" in output

    def test_unique_items_cannot_be_excepted(self):
        """The API server rejects the CRD outright, so no reason makes it work."""
        exc = self.exceptions_file("uniqueItems:\n  - {field: spec.routes, reason: frozen}\n")
        code, output = run([FIXTURES / "trial-gateway.yaml"], exceptions=exc)
        assert code == c.EXIT_NO_CORPUS
        assert "uniqueItems cannot be excepted" in output

    def test_report_only_prints_findings_and_exits_clean(self):
        out = io.StringIO()
        code = c.run([str(FIXTURES / "bad.yaml")], out=out, report_only=True)
        output = out.getvalue()
        assert code == c.EXIT_CLEAN, output
        assert "FAIL:   " in output
        assert "report only, findings do not fail the run" in output

    def test_report_only_still_fails_on_extraction_error(self):
        """Report-only must never turn an empty corpus into a pass."""
        out = io.StringIO()
        code = c.run([str(self.tmp() / "nosuch.yaml")], out=out, report_only=True)
        assert code == c.EXIT_NO_CORPUS

    def test_report_only_flag_on_the_command_line(self):
        cwd = os.getcwd()
        os.chdir(self.tmp())  # no ./xrd-schema-exceptions.yaml here
        self.addCleanup(os.chdir, cwd)
        with contextlib.redirect_stdout(io.StringIO()):
            plain = c.main([str(FIXTURES / "bad.yaml")])
            report_only = c.main(["--report-only", str(FIXTURES / "bad.yaml")])
        assert plain == c.EXIT_FINDINGS
        assert report_only == c.EXIT_CLEAN

    # ---------------------------------------------------------------------------
    # Scoped exceptions: one frozen XRD version must not waive the same finding
    # in every other XRD and version, where it can still be fixed
    # ---------------------------------------------------------------------------

    TLS = "spec.tlsConfig.minVersion"

    def project(self):
        """Two XRDs, each with v1alpha1 and v1beta1, each version carrying the
        same lowercase enum: one finding key, four places. The working directory
        is the project root, so findings print `apis/<x>/definition.yaml[...]`."""
        root = self.tmp()
        for name, group, kind in (("a", "alpha", "Repository"), ("b", "bravo", "Mirror")):
            doc = yaml.safe_load((FIXTURES / "good.yaml").read_text())
            doc["metadata"]["name"] = f"{kind.lower()}s.{group}.example.com"
            doc["spec"]["group"] = f"{group}.example.com"
            doc["spec"]["names"] = {"kind": kind, "plural": f"{kind.lower()}s"}
            v1 = doc["spec"]["versions"][0]
            spec = v1["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
            spec["tlsConfig"]["properties"]["minVersion"]["enum"] = ["tls12", "tls13"]
            v2 = copy.deepcopy(v1)
            v2["name"] = "v1beta1"
            doc["spec"]["versions"].append(v2)
            xrd = root / "apis" / name / "definition.yaml"
            xrd.parent.mkdir(parents=True)
            xrd.write_text(yaml.safe_dump(doc))
        cwd = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, cwd)
        return ["apis/*/definition.yaml"]

    def scoped(self, *fields):
        return self.exceptions_file(
            "enumCasing:\n"
            + "".join(f"  - {{field: '{f}', reason: frozen {i}}}\n" for i, f in enumerate(fields))
        )

    @staticmethod
    def places(output, prefix):
        """The `<file>[<version>]` of every line starting with `prefix`."""
        return {
            ln[len(prefix):].split(".spec.", 1)[0]
            for ln in output.splitlines() if ln.startswith(prefix)
        }

    ALL = {
        "apis/a/definition.yaml[v1alpha1]", "apis/a/definition.yaml[v1beta1]",
        "apis/b/definition.yaml[v1alpha1]", "apis/b/definition.yaml[v1beta1]",
    }

    def test_qualified_exception_applies_to_its_file_and_version_only(self):
        paths = self.project()
        exc = self.scoped(f"apis/a/definition.yaml[v1alpha1].{self.TLS}")
        code, output = run(paths, exceptions=exc)
        assert code == c.EXIT_FINDINGS, output
        assert self.places(output, "EXCEPTED: ") == {"apis/a/definition.yaml[v1alpha1]"}
        assert self.places(output, "FAIL:   ") == self.ALL - {"apis/a/definition.yaml[v1alpha1]"}
        assert "matches no finding" not in output and "has no file or version" not in output

    def test_qualified_file_matches_however_the_path_was_spelt(self):
        """`./apis/a/...` in the entry and `apis/a/...` on the command line are one file."""
        paths = self.project()
        exc = self.scoped(f"./apis/a/definition.yaml[v1alpha1].{self.TLS}")
        _code, output = run(paths, exceptions=exc)
        assert self.places(output, "EXCEPTED: ") == {"apis/a/definition.yaml[v1alpha1]"}

    def test_wildcard_version_covers_every_version_of_one_file(self):
        paths = self.project()
        _code, output = run(paths, exceptions=self.scoped(f"apis/a/definition.yaml[*].{self.TLS}"))
        assert self.places(output, "EXCEPTED: ") == {
            "apis/a/definition.yaml[v1alpha1]", "apis/a/definition.yaml[v1beta1]",
        }
        assert all(p.startswith("apis/b/") for p in self.places(output, "FAIL:   "))

    def test_wildcard_file_covers_one_version_of_every_file(self):
        paths = self.project()
        _code, output = run(paths, exceptions=self.scoped(f"*[v1beta1].{self.TLS}"))
        assert self.places(output, "EXCEPTED: ") == {
            "apis/a/definition.yaml[v1beta1]", "apis/b/definition.yaml[v1beta1]",
        }

    def test_explicit_project_wide_exception_is_clean_and_not_reviewed(self):
        """`*[*].` says on purpose what a bare path says by accident."""
        paths = self.project()
        code, output = run(paths, exceptions=self.scoped(f"*[*].{self.TLS}"))
        assert code == c.EXIT_CLEAN, output
        assert self.places(output, "EXCEPTED: ") == self.ALL
        assert "REVIEW:" not in output

    def test_bare_exception_still_applies_everywhere_but_names_the_places(self):
        """Existing files keep working; the reach of a bare entry is surfaced."""
        paths = self.project()
        code, output = run(paths, exceptions=self.scoped(self.TLS))
        assert code == c.EXIT_CLEAN, output
        assert self.places(output, "EXCEPTED: ") == self.ALL
        review = [ln for ln in output.splitlines()
                  if ln.startswith("REVIEW:") and "has no file or version" in ln]
        assert len(review) == 1, output
        assert "excepts 4 places" in review[0]
        for place in self.ALL:
            assert place in review[0], place
        assert f"*[*].{self.TLS}" in review[0]

    def test_bare_exception_in_one_place_is_not_reviewed(self):
        exc = self.exceptions_file(
            "enumCasing:\n  - {field: spec.packageType, reason: registry spellings}\n"
        )
        _code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert "EXCEPTED: " in output
        assert "has no file or version" not in output

    def test_stale_qualified_exception_is_reported(self):
        paths = self.project()
        exc = self.scoped(f"apis/a/definition.yaml[v9].{self.TLS}")
        code, output = run(paths, exceptions=exc)
        assert code == c.EXIT_FINDINGS
        assert self.places(output, "FAIL:   ") == self.ALL
        assert any(
            ln.startswith("REVIEW:")
            and f"'apis/a/definition.yaml[v9].{self.TLS}' matches no finding" in ln
            for ln in output.splitlines()
        ), output

    def test_most_specific_entry_gives_the_reason(self):
        paths = self.project()
        exc = self.scoped(f"*[*].{self.TLS}", f"apis/a/definition.yaml[v1alpha1].{self.TLS}")
        code, output = run(paths, exceptions=exc)
        assert code == c.EXIT_CLEAN, output
        for ln in output.splitlines():
            if ln.startswith("EXCEPTED: "):
                specific = ln.startswith("EXCEPTED: apis/a/definition.yaml[v1alpha1]")
                assert ln.endswith("-- frozen 1" if specific else "-- frozen 0"), ln
        assert "REVIEW:" not in output

    def test_entry_wholly_covered_by_a_more_specific_one_is_reported(self):
        paths = self.project()
        exc = self.scoped(
            f"apis/a/definition.yaml[*].{self.TLS}",
            f"apis/a/definition.yaml[v1alpha1].{self.TLS}",
            f"apis/a/definition.yaml[v1beta1].{self.TLS}",
        )
        _code, output = run(paths, exceptions=exc)
        assert any(
            ln.startswith("REVIEW:") and f"'apis/a/definition.yaml[*].{self.TLS}' is shadowed"
            in ln for ln in output.splitlines()
        ), output

    def test_bare_path_through_a_list_is_not_mistaken_for_a_scope(self):
        """`spec.rules[].port` has `[]`, not `[<version>]`: it stays a bare path."""
        e = c.parse_entry("x", "maxItems", 0, "spec.rules[].ports", "r")
        assert (e.file, e.version, e.key) == (None, None, "spec.rules[].ports")
        e = c.parse_entry("x", "maxItems", 0, "apis/x.yaml[v1].spec.rules[].ports", "r")
        assert (e.file, e.version, e.key) == ("apis/x.yaml", "v1", "spec.rules[].ports")

    def test_printer_column_is_scoped_to_file_and_version(self):
        bad = str(FIXTURES / "bad.yaml")
        exc = self.exceptions_file(
            f"printerColumn:\n  - {{field: '{bad}[v1alpha1].READY', reason: frozen}}\n"
        )
        _code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert any(ln.startswith("EXCEPTED: ") and "printer column READY" in ln
                   for ln in output.splitlines()), output
        exc = self.exceptions_file(
            f"printerColumn:\n  - {{field: '{bad}[v2].READY', reason: frozen}}\n"
        )
        _code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert any(ln.startswith("FAIL:   ") and "printer column READY" in ln
                   for ln in output.splitlines()), output

    def test_kind_acronym_is_scoped_to_a_file_and_rejects_a_version(self):
        """A Kind spans every version, so naming one is a mistake worth stopping on."""
        kind = str(FIXTURES / "kind.yaml")
        exc = self.exceptions_file(
            f"kindAcronym:\n  - {{field: '{kind}[*].HttpLoadbalancer', reason: frozen}}\n"
        )
        _code, output = run([FIXTURES / "kind.yaml"], exceptions=exc)
        assert any(ln.startswith("EXCEPTED: ") and "Kind 'HttpLoadbalancer'" in ln
                   for ln in output.splitlines()), output
        exc = self.exceptions_file(
            f"kindAcronym:\n  - {{field: '{kind}[v1alpha1].HttpLoadbalancer', reason: frozen}}\n"
        )
        code, output = run([FIXTURES / "kind.yaml"], exceptions=exc)
        assert code == c.EXIT_NO_CORPUS
        assert "a Kind spans every version" in output

    def test_collision_rejects_a_file_scope(self):
        exc = self.exceptions_file(
            "collision:\n  - {field: 'apis/x.yaml[*].ProjectId / projectID', reason: frozen}\n"
        )
        code, output = run([FIXTURES / "bad.yaml"], exceptions=exc)
        assert code == c.EXIT_NO_CORPUS
        assert "a collision spans the whole corpus" in output


def run_without_yaml(*args: str) -> subprocess.CompletedProcess:
    """Run the script as a program in a Python where `import yaml` fails."""
    # A None entry in sys.modules makes the import raise ImportError, whether
    # or not PyYAML is installed here.
    prog = ("import runpy, sys; sys.modules['yaml'] = None; "
            "sys.argv = sys.argv[1:]; "
            "runpy.run_path(sys.argv[0], run_name='__main__')")
    return subprocess.run(
        [sys.executable, "-I", "-c", prog, str(SCRIPTS / "check_xrd_schema.py"), *args],
        capture_output=True, text=True, timeout=60,
    )


class WithoutPyYamlTest(unittest.TestCase):
    """PyYAML is imported lazily: help works without it, a check fails loudly."""

    def test_help_works_without_pyyaml(self):
        proc = run_without_yaml("--help")
        assert proc.returncode == 0, proc.stderr
        assert "usage:" in proc.stdout

    def test_missing_pyyaml_is_one_line_and_exit_2(self):
        proc = run_without_yaml(str(FIXTURES / "good.yaml"))
        assert proc.returncode == 2, (proc.stdout, proc.stderr)
        lines = proc.stderr.strip().splitlines()
        assert len(lines) == 1 and "PyYAML is not installed" in lines[0], proc.stderr
        assert "Traceback" not in proc.stderr
