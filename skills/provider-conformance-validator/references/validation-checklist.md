# Provider Conformance Validation Checklist

Use this to validate a Crossplane provider repository against the conformance rules. It is written to be run by an agent or a human reviewer against a checked-out repository. Each rule is a discrete check with explicit pass and fail signals, the artifacts to inspect, a result box, and an evidence line.

## How to use this

1. **Check out the repository** at the commit under review. Work rule by rule, in order.
2. **Gather evidence before deciding.** Do not mark PASS on assumption. Every PASS must cite a concrete artifact: a file path, a schema field, a CI job, a command output, or a test result. Every FAIL must cite what is missing or wrong.
3. **Record a result per rule:** `PASS`, `FAIL`, or `N/A`. `N/A` is only valid when the rule does not apply (e.g. conversion rules for a single-version provider) and must state why; an untested resource is not `N/A`, it is a `FAIL` of TST-4 unless it appears in the coverage register.
4. **Static vs dynamic.** Most checks are static and can be answered from the source, generated manifests, and CI configuration. Where a check is dynamic (requires running e2e or conversion tests), verify instead that the repository contains and wires the test in CI; note that live execution was not performed.
5. **Verdict.** The provider is conformant only if there are zero `FAIL` results and every `N/A` is justified. A single unresolved `FAIL` on any rule means non-conformant.
6. **Output.** Produce the filled per-rule results with evidence, then the summary scorecard at the end, then a one-line verdict.

## Output contract (what the agent should return)

For each rule, emit:

```
<RULE-ID> — <PASS|FAIL|N/A>
  evidence: <file/schema/CI/command reference>
  notes: <only if FAIL or N/A: what is missing/wrong, or why N/A>
```

Then the summary scorecard, then: `VERDICT: CONFORMANT` or `VERDICT: NON-CONFORMANT (<n> failing rules: <ids>)`.

## Quick signal collection (optional first pass)

These commands surface many signals at once. Adapt paths to the repo layout.

```bash
# Regeneration determinism (GEN-1, GEN-2): expect an empty diff
make generate >/dev/null 2>&1; git status --porcelain

# Generated-file markers (GEN-2)
grep -rl "DO NOT EDIT" apis/ | head

# CRD manifests: locate them
find . -path '*/crds/*.yaml' -o -name '*.yaml' | xargs grep -l "kind: CustomResourceDefinition" 2>/dev/null | head

# Spec structure (SCH-2): forProvider / initProvider / atProvider
grep -rl "forProvider" apis/ | head; grep -rl "initProvider" apis/ | head

# Presentation (SCH-5): printer columns + categories
grep -rn "EXTERNAL-NAME\|additionalPrinterColumns\|categories" package/ apis/ 2>/dev/null | head

# External-name configs (RT-1) and not-tested register (TST-4)
ls config/externalname*.go 2>/dev/null; ls config/*nottested* 2>/dev/null

# ProviderConfig (PC-1..3)
find apis -iname '*providerconfig*' | head

# Multiple versions + storage + deprecation (EVO-2/4/5)
grep -rn "storage: true\|deprecated: true" . 2>/dev/null | head

# CI: e2e, conversion, breaking-change, signing (TST-1/2, EVO-6, PKG-2)
ls .github/workflows/ 2>/dev/null; grep -rniE "uptest|crddiff|cosign|sbom|conversion|roundtrip" .github/ 2>/dev/null | head -20

# Governance (GOV-1)
ls OWNERS* CODEOWNERS 2>/dev/null
```

---

## Schema and API design

### SCH-1 — Consistent naming  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Field and type names use the shared casing and canonical acronym forms; names are derived from the API, not raw source casing.
- **Inspect:** `apis/**/*_types.go` and the generated CRD schemas.
- **Pass if:** acronyms are cased canonically (IPv6, TLS, ARN, ID, URL) and fields are lowerCamelCase throughout.
- **Fail if:** mixed casings for the same concept, or mis-cased acronyms (e.g. `Ipv6`, `Tls`, `CIDRBlock` vs `CidrBlock`) appear. Grep signal: `grep -rnE "Ipv6|IPV6|Url[A-Z]|Tls[A-Z]|Api[A-Z]" apis/`.
- **Evidence:** _______________________

### SCH-2 — Separated spec  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Each resource separates desired configuration, creation-only values, and observed state.
- **Inspect:** each `*_types.go` for `ForProvider`, `InitProvider`, and observation (`AtProvider`) structs; CRD for `spec.forProvider`, `spec.initProvider`, `status.atProvider`.
- **Pass if:** all three sections exist and observed-only values live under status, not spec.
- **Fail if:** a cloud-assigned/observed value appears under `spec.forProvider`, or `initProvider` is absent where creation-only values exist.
- **Evidence:** _______________________

### SCH-3 — Policy-aware requiredness  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Required fields are conditional on the management policy, not statically required.
- **Inspect:** CRD `openAPIV3Schema` for `x-kubernetes-validations` rules referencing `managementPolicies`; confirm no create-time `forProvider` field sits in an unconditional `required:` list.
- **Pass if:** requiredness is expressed via a CEL validation predicated on the policy and satisfiable from `forProvider` or `initProvider`.
- **Fail if:** a create-required field is in a plain `required:` array, so observe-only/import objects are rejected at admission.
- **Evidence:** _______________________

### SCH-4 — Declared validation  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Enums, formats, ranges, immutability, and defaults are declared on the API.
- **Inspect:** CRD schema for `enum`, `format`, `pattern`, `minimum`/`maximum`; type markers for immutability/defaults.
- **Pass if:** constrained fields carry declared validation the API server enforces at admission.
- **Fail if:** known enumerated/bounded fields accept arbitrary input, deferring failure to reconcile.
- **Evidence:** _______________________

### SCH-5 — Consistent presentation  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Status subresource, standard printer columns, and standard categories are present.
- **Inspect:** CRD for `subresources.status`, `additionalPrinterColumns` (SYNCED, READY, EXTERNAL-NAME, AGE), and `categories` including `crossplane`/`managed`.
- **Pass if:** all resources expose the standard columns and categories.
- **Fail if:** any resource lacks the status subresource, the standard columns, or the categories.
- **Evidence:** _______________________

### SCH-6 — Stable grouping  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** One service per group under a stable domain; group/kind unchanged since prior release.
- **Inspect:** `apis/` directory structure and group strings; compare against the last released tag for any group/kind rename.
- **Pass if:** groups follow `<service>.<provider>.<domain>`, namespaced variants under a parallel domain, with no group/kind moved since release.
- **Fail if:** per-resource or inconsistent groups, or a group/kind changed for an existing kind.
- **Evidence:** _______________________

### SCH-7 — Deliberate scope  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Scope is chosen deliberately; cluster and namespaced forms are at parity where both exist.
- **Inspect:** CRD `scope`; if both `apis/cluster` and `apis/namespaced` (or equivalent) exist, diff their schemas per kind.
- **Pass if:** each kind's scopes share identical schema and behavior, differing only in scope/domain.
- **Fail if:** the namespaced form omits or diverges from fields present in the cluster form.
- **Evidence:** _______________________

## Runtime behavior

### RT-1 — External name  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Every resource has a correct external-name configuration; import re-adopts from the external name alone.
- **Inspect:** `config/externalname.go` (and any not-tested register) for a per-resource entry; CI for the uptest import step.
- **Pass if:** each resource has an external-name strategy configured, and the import test re-adopts the live resource.
- **Fail if:** resources are missing external-name configuration, or the import test creates a duplicate / is absent.
- **Evidence:** _______________________

### RT-2 — Crash-safe create  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Create records identity before/around the external call so an interrupted create is not duplicated.
- **Inspect:** reconciler wiring uses the standard managed reconciler (create-pending protocol) rather than a custom `Create` that bypasses it; review any custom `Create`.
- **Pass if:** the provider relies on the standard managed reconciler / Upjet runtime for create, or a custom create implements the pending protocol.
- **Fail if:** a custom `Create` writes the external resource without recording pending state, or discards the recorded identity.
- **Evidence:** _______________________

### RT-3 — Read-only observation  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Observation performs no external writes and reports existence, up-to-dateness, and connection details.
- **Inspect:** generated/inherited observe path (automatic under Upjet); review any custom `Observe`.
- **Pass if:** observation is a pure read via the standard runtime, or a custom `Observe` performs no writes.
- **Fail if:** a custom `Observe` mutates the external resource or fabricates up-to-dateness.
- **Evidence:** _______________________

### RT-4 — Bounded late-initialization  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Late-init occurs only when it changes the spec, never every pass, never over user values.
- **Inspect:** inherited late-init (Upjet) or custom `LateInitialize`; steady-state behavior in e2e (object generation stable after convergence).
- **Pass if:** standard late-init is used, or a custom implementation is conditional and non-overwriting.
- **Fail if:** a custom late-init reports change unconditionally, or the object's generation keeps incrementing at steady state.
- **Evidence:** _______________________

### RT-5 — Management policies  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** The controller honors managementPolicies and takes no excluded action.
- **Inspect:** managementPolicies exposed on CRDs; reconciler enabled with management-policy support; uptest step under a restricted policy (e.g. ObserveOnly).
- **Pass if:** the CRD exposes `managementPolicies` and the runtime gates actions on it.
- **Fail if:** management policies are unsupported/ignored, or a restricted-policy test shows an excluded action.
- **Evidence:** _______________________

### RT-6 — Not-found  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Absence is distinguished from error; deletion completes on out-of-band removal.
- **Inspect:** not-found handling config where the backend signals absence as an error; uptest delete step (and out-of-band-delete if present).
- **Pass if:** absence maps to not-found and deletion finalizes cleanly.
- **Fail if:** absence surfaces as an error, hanging deletion, or a resource is recreated after external deletion.
- **Evidence:** _______________________

### RT-7 — Secret handling  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Sensitive values go only to the connection secret, never spec/status.
- **Inspect:** connection-detail configuration; grep types/CRD to confirm no sensitive fields in `status`; e2e confirms the connection secret is populated.
- **Pass if:** sensitive values are mapped to the connection secret and absent from spec/status.
- **Fail if:** a password/token/key appears in spec or status.
- **Evidence:** _______________________

### RT-8 — Asynchronous operations  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Long operations poll within declared timeouts and do not block the worker.
- **Inspect:** async/operation-timeout configuration for long-running resources; e2e completes without controller stalls.
- **Pass if:** long resources are configured async with declared timeouts.
- **Fail if:** a long-running create/delete blocks the reconcile worker.
- **Evidence:** _______________________

## ProviderConfig and credentials

### PC-1 — Standard configuration  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** A ProviderConfig API of the standard shape exists.
- **Inspect:** `apis/**/providerconfig` types.
- **Pass if:** a ProviderConfig matching the ecosystem shape is present.
- **Fail if:** no ProviderConfig, or a bespoke configuration model.
- **Evidence:** _______________________

### PC-2 — Standard credential sources  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Secret, filesystem, environment, and injected identity are supported.
- **Inspect:** ProviderConfig credential source handling / enum.
- **Pass if:** all standard sources are supported.
- **Fail if:** only an idiosyncratic subset (e.g. secret-only) is supported.
- **Evidence:** _______________________

### PC-3 — In-use protection  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** A referenced ProviderConfig cannot be deleted; in-use state is observable.
- **Inspect:** usage tracking + finalizer wiring; a delete-while-referenced test if present.
- **Pass if:** usage accounting and the in-use finalizer are wired.
- **Fail if:** a ProviderConfig can be deleted while resources reference it.
- **Evidence:** _______________________

## API evolution, storage, and migration

### EVO-1 — Version stability tiers  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** version names across `apis/**`; changelog/git history for changes to `v1beta1`+ versions vs `v1alpha1`.
- **Pass if:** stable versions (`v1beta1`+) show only additive changes; iteration happens in `v1alpha1`.
- **Fail if:** a served `v1beta1`+ version received a breaking change, or alpha is treated as permanent.
- **Evidence:** _______________________

### EVO-2 — No in-place breakage  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** breaking-change check output comparing served schemas against the last released tag.
- **Pass if:** changes to existing stable versions are additive-only.
- **Fail if:** a field was renamed, removed, retyped, or newly required in a served stable version.
- **Evidence:** _______________________

### EVO-3 — Breaking changes go to a new version  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** `apis/**` for multiple versions; confirm a breaking change corresponds to a new version, not an edited one.
- **Pass if:** breaking changes appear as new versions with prior versions still served.
- **Fail if:** a breaking change edited an existing version, or a served version was dropped out of process.
- **Evidence:** _______________________

### EVO-4 — Conversion completeness and strategy  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** conversion registrations (e.g. `config/` conversion wiring / registry); CRD `spec.conversion.strategy`.
- **Pass if:** every served-version pair has a registered conversion and `strategy: Webhook` is set wherever served schemas differ.
- **Fail if:** a pair is missing a conversion, structural changes are hand-rolled outside the registry, or a schema-differing CRD uses `strategy: None`. Grep signal: `grep -rn "strategy: None" <crd-dir>`.
- **Evidence:** _______________________

### EVO-5 — Lossless round-trip with data preservation  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** round-trip/fuzz conversion tests; confirm newer-version-only fields are preserved (annotation-based or equivalent) and exercised by the tests.
- **Pass if:** round-trip tests over generated inputs cover every version pair, populate newer-version-only fields, and assert identity.
- **Fail if:** conversions exist without round-trip tests, or a newer-version-only field is dropped through an older version. `N/A` only for a single served version everywhere.
- **Evidence:** _______________________

### EVO-6 — Single storage version  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** each CRD's versions for exactly one `storage: true`; confirm it is the most expressive version.
- **Pass if:** one storage version per CRD, able to represent all served versions.
- **Fail if:** zero or multiple storage versions, or a storage version that cannot represent another served version. Grep signal: per CRD, count `storage: true`.
- **Evidence:** _______________________

### EVO-7 — Storage promotion lags introduction  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** compare the storage version in this release against the versions served (non-storage) in the prior release.
- **Pass if:** the current storage version was served (non-storage) in the prior release, not introduced in this one.
- **Fail if:** a version is introduced and made storage in the same release.
- **Evidence:** _______________________

### EVO-8 — Downgrade safety  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** presence of a downgrade read test (write with current, read at prior release's served version); otherwise reason about EVO-5/6/7 coverage.
- **Pass if:** a test or clear guarantee shows the prior release can read all objects the current release can store.
- **Fail if:** no downgrade coverage and the storage version outpaces the prior release's understanding.
- **Evidence:** _______________________

### EVO-9 — Safe version removal  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** for any version removed since the last release, confirm a storage-version migration ran and the version was cleared from `status.storedVersions` before removal from `spec.versions`.
- **Pass if:** removed versions followed migrate then clear `storedVersions` then drop from `spec.versions`.
- **Fail if:** a version was dropped from `spec.versions` while still in `status.storedVersions`, or with no migration. `N/A` if no version has been removed.
- **Evidence:** _______________________

### EVO-10 — Deprecate before removal  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** `deprecated: true` and `deprecationWarning` on superseded versions; changelog for the deprecation release and window.
- **Pass if:** removed/removing versions went through deprecation, warning, and a served window.
- **Fail if:** a version was removed with no prior deprecation or window. `N/A` if nothing has been superseded.
- **Evidence:** _______________________

### EVO-11 — Versioning review gate  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Inspect:** CI for a breaking-change check, conversion round-trip tests, and any storage/version transition review; confirm the gate is not bypassed.
- **Pass if:** breaking-change and round-trip checks run on PRs and new versions cannot merge without conversions and passing tests.
- **Fail if:** no breaking-change check, no round-trip gate, or the checks are suppressed to merge.
- **Evidence:** _______________________

## Generation determinism

### GEN-1 — Reproducible  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Regenerating from the same inputs yields identical output.
- **Inspect:** run the generate target, then `git status --porcelain`.
- **Pass if:** regeneration produces an empty diff.
- **Fail if:** regeneration produces any spurious diff (reordering, timestamps). `N/A` only for a fully hand-written provider.
- **Evidence:** _______________________

### GEN-2 — No hand-edits  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Generated artifacts are not hand-edited.
- **Inspect:** generated files carry a "DO NOT EDIT" marker; the GEN-1 regenerate-and-diff also catches edits.
- **Pass if:** regeneration leaves generated files unchanged (no hand-edits present).
- **Fail if:** regeneration reverts changes in generated files, indicating hand-edits.
- **Evidence:** _______________________

## Packaging and supply chain

### PKG-1 — Valid package  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Builds a valid package with complete metadata (capabilities, family).
- **Inspect:** package metadata (`crossplane.yaml`/package manifest); build target produces a valid package.
- **Pass if:** metadata is complete and the package builds/validates.
- **Fail if:** missing/incorrect metadata, or the package fails to build/validate.
- **Evidence:** _______________________

### PKG-2 — Signed and attested  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Releases are signed with provenance attestation and an SBOM.
- **Inspect:** release workflow for signing (e.g. cosign), attestation, and SBOM generation.
- **Pass if:** the release pipeline signs, attests, and emits an SBOM.
- **Fail if:** releases are unsigned, or lack attestation/SBOM.
- **Evidence:** _______________________

### PKG-3 — Vulnerability response  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Vulnerabilities are tracked and patched on a defined cadence; patched releases meet all rules.
- **Inspect:** dependency scanning / update automation (e.g. dependabot/renovate, image scan) in CI; documented CVE process.
- **Pass if:** scanning and a remediation cadence exist and produce signed, attested patch releases.
- **Fail if:** no scanning/process, or known unpatched vulnerabilities past the window.
- **Evidence:** _______________________

## Observability and status

### OBS-1 — Standard conditions  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Standard Ready and Synced conditions with standard reasons, reflecting real state.
- **Inspect:** inherited from the standard runtime; e2e asserts conditions across the lifecycle.
- **Pass if:** resources report Ready/Synced with standard reasons that track external state.
- **Fail if:** conditions are missing, non-standard, or readiness is true before the resource is usable.
- **Evidence:** _______________________

### OBS-2 — Standard metrics  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Standard resource-level metrics are exposed unmodified.
- **Inspect:** metrics endpoint / runtime wiring; confirm standard metrics are not suppressed or renamed.
- **Pass if:** the standard metrics (time to reconcile/readiness, drift, deletion, external-call volume/latency) are present.
- **Fail if:** standard metrics are renamed, dropped, or replaced.
- **Evidence:** _______________________

### OBS-3 — Events  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Events are emitted for lifecycle transitions and reconcile errors with cause.
- **Inspect:** event emission (inherited or custom); e2e/error-path shows events on the object.
- **Pass if:** significant transitions and errors surface as events with a cause.
- **Fail if:** failures are visible only in controller logs.
- **Evidence:** _______________________

## Security

### SEC-1 — Least privilege  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Least-privilege permissions requested and documented.
- **Inspect:** deployment RBAC/permission scope and docs on required permissions.
- **Pass if:** permissions are scoped to what the provider manages and documented.
- **Fail if:** account-wide/administrative permissions are requested, or undocumented.
- **Evidence:** _______________________

### SEC-2 — No secret leakage  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** No secrets in logs, spec, status, or events.
- **Inspect:** grep log statements for sensitive fields; confirm sensitive fields are not in status; review debug/trace logging.
- **Pass if:** sensitive values are confined to the connection secret at every verbosity.
- **Fail if:** a credential is logged or mirrored into spec/status/events.
- **Evidence:** _______________________

## Testing

### TST-1 — Lifecycle proof  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Every testable resource has an e2e test covering create, update, import, delete.
- **Inspect:** CI wires the e2e lifecycle (e.g. uptest) over the examples; import step present.
- **Pass if:** the four-step lifecycle runs in CI for testable resources.
- **Fail if:** no e2e lifecycle, or the import/delete steps are missing.
- **Evidence:** _______________________

### TST-2 — Conversion proof  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Version conversions are round-trip tested in CI.
- **Inspect:** conversion round-trip test presence and CI wiring (mirrors EVO-3).
- **Pass if:** round-trip conversion tests run in CI.
- **Fail if:** conversions exist without tests. `N/A` for a single-version provider.
- **Evidence:** _______________________

### TST-3 — Examples  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Every resource ships a deployable, dependency-complete example.
- **Inspect:** `examples-generated/` (or equivalent) has an example per resource, with dependencies.
- **Pass if:** each resource has an example that applies cleanly with its dependencies.
- **Fail if:** resources lack examples, or examples reference undeclared dependencies.
- **Evidence:** _______________________

### TST-4 — Declared exceptions  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Untested resources are declared with a reason in a coverage register.
- **Inspect:** the not-tested register (e.g. a not-tested external-name file / uptest skip list) with reasons.
- **Pass if:** every untested resource has a register entry with justification.
- **Fail if:** any resource is untested and not recorded.
- **Evidence:** _______________________

## Governance and maintenance

### GOV-1 — Named ownership  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Maintainers and review owners are declared.
- **Inspect:** `OWNERS` / `CODEOWNERS`.
- **Pass if:** an ownership record names maintainers and reviewers.
- **Fail if:** no declared ownership.
- **Evidence:** _______________________

### GOV-2 — Supported releases  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Releases come from maintained lines with backports.
- **Inspect:** release branches/tags; backport workflow or documented policy.
- **Pass if:** maintained release lines exist and fixes are backportable.
- **Fail if:** releases only from head with no backport path.
- **Evidence:** _______________________

### GOV-3 — Maintenance parity  `☐ PASS  ☐ FAIL  ☐ N/A`
- **Check:** Maintenance changes pass the same gate as new work.
- **Inspect:** CI runs the full gate (tests, generation, breaking-change) on all PRs, with no maintenance bypass.
- **Pass if:** the conformance gate runs on every change.
- **Fail if:** a lighter path exists for maintenance changes.
- **Evidence:** _______________________

---

## Summary scorecard

Fill the result for each rule. The provider is conformant only with zero `FAIL` and every `N/A` justified.

| Rule | Result | Rule | Result | Rule | Result |
|---|---|---|---|---|---|
| SCH-1 |   | SCH-2 |   | SCH-3 |   |
| SCH-4 |   | SCH-5 |   | SCH-6 |   |
| SCH-7 |   | RT-1 |   | RT-2 |   |
| RT-3 |   | RT-4 |   | RT-5 |   |
| RT-6 |   | RT-7 |   | RT-8 |   |
| PC-1 |   | PC-2 |   | PC-3 |   |
| EVO-1 |   | EVO-2 |   | EVO-3 |   |
| EVO-4 |   | EVO-5 |   | EVO-6 |   |
| EVO-7 |   | EVO-8 |   | EVO-9 |   |
| EVO-10 |   | EVO-11 |   | GEN-1 |   |
| GEN-2 |   | PKG-1 |   | PKG-2 |   |
| PKG-3 |   | OBS-1 |   | OBS-2 |   |
| OBS-3 |   | SEC-1 |   | SEC-2 |   |
| TST-1 |   | TST-2 |   | TST-3 |   |
| TST-4 |   | GOV-1 |   | GOV-2 |   |
| GOV-3 |   |  |   |  |   |

**Totals:** PASS ___ / FAIL ___ / N/A ___

**VERDICT:** `CONFORMANT` or `NON-CONFORMANT (failing: <rule ids>)`
