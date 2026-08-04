---
name: provider-conformance-validator
description: Validate a Crossplane or Upjet provider repository against the provider conformance standard and produce a conformance report. Covers schema and API design, runtime behavior (external name, crash-safe create, late-init, management policies, not-found, secrets, async), ProviderConfig and credentials, API versioning and storage/migration (no-break, conversion, single storage version, storage-promotion lag, downgrade safety, storedVersions removal, deprecation), generation determinism, packaging and supply chain, observability, security, testing, and governance. Use when asked to audit, review, or check a provider repo for conformance; to verify API versioning, storage-version, or upgrade/downgrade safety; or to produce a conformance scorecard or verdict.
license: Apache-2.0
---

# Provider Conformance Validator

This skill validates a Crossplane provider repository against the conformance standard and produces a scorecard and verdict. It is engine-agnostic (Upjet-generated or hand-written) but its inspection hints assume a typical Upjet provider layout; adapt paths as needed.

## Files in this skill

- `references/conformance-rules.md` — the normative standard: 46 rules across ten areas, each with rationale and accepted/conformant/non-conformant values. This is the source of truth for what each rule means.
- `references/validation-checklist.md` — the per-rule checks (what to inspect, pass/fail signals) and the summary scorecard to fill in. This is what you execute.

Read `validation-checklist.md` in full before starting. Consult `conformance-rules.md` whenever a rule's intent or a borderline pass/fail decision is unclear.

## How to run a validation

1. **Establish the target.** Confirm the repository and commit under review are checked out and readable. If validating versioning/upgrade rules (EVO-7, EVO-8, EVO-9), also identify the previous released tag, since several checks compare the current state against the prior release.

2. **Collect signals first.** Run the quick signal-collection commands at the top of `validation-checklist.md` (regeneration diff, CRD inspection, external-name configs, ProviderConfig, version/storage/deprecation markers, CI workflows, ownership files). Capture the output; it feeds many checks at once.

3. **Work rule by rule, in order.** For each of the 46 checks in `validation-checklist.md`, inspect the named artifacts, decide `PASS`, `FAIL`, or `N/A`, and record concrete evidence. Rules of evidence:
   - Never mark `PASS` on assumption. Cite a file path, a schema field, a CI job, a command output, or a test result.
   - Every `FAIL` names what is missing or wrong.
   - `N/A` is valid only when the rule genuinely does not apply (e.g. conversion rules for a single-version provider) and must state why. An untested resource is not `N/A`; it is a `FAIL` of TST-4 unless it appears in the coverage register.

4. **Static vs dynamic.** Most checks are answerable statically from source, generated manifests, and CI configuration. For dynamic checks (e2e lifecycle, conversion round-trips, downgrade reads), verify that the repository contains and wires the test in CI, and note that live execution was not performed. Do not fabricate a pass for a test you did not run.

5. **Pay special attention to the versioning and storage rules (EVO-1 through EVO-11).** These are the checks most often missed and the ones with the largest blast radius:
   - EVO-4: a multi-version CRD whose schemas differ must use `strategy: Webhook`, never `None`. Grep the CRDs for `strategy: None`.
   - EVO-6: exactly one `storage: true` per CRD.
   - EVO-7: the current storage version must have been served (non-storage) in the prior release, not introduced in this one. This is what makes downgrade safe.
   - EVO-9: any version removed since the prior release must have been migrated and cleared from `status.storedVersions` before being dropped from `spec.versions`. A version dropped while still in `storedVersions` renders stored objects unreadable.

6. **Produce the report.** For each rule emit:
   ```
   <RULE-ID> — <PASS|FAIL|N/A>
     evidence: <reference>
     notes: <only if FAIL or N/A>
   ```
   Then fill the summary scorecard from `validation-checklist.md`, then end with:
   `VERDICT: CONFORMANT` or `VERDICT: NON-CONFORMANT (<n> failing: <ids>)`.

## Verdict rule

The provider is conformant only if there are zero `FAIL` results and every `N/A` is justified. A single unresolved `FAIL` on any rule means non-conformant. Do not soften a `FAIL` into an `N/A` to reach a passing verdict; report the failure plainly with its evidence.

## Judgment calls

A few rules are qualitative and cannot be decided purely mechanically (e.g. PC-1 standard configuration shape, SCH-1 naming consistency at the margins, SEC-1 least privilege, GOV-2 supported releases). Make a call from the evidence, cite it, and flag these explicitly as reviewer-judgment items in the notes so a human can confirm.
