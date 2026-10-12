# Migration checklist template

Write the plan to `.agents/plans/CROSSPLANE_V2_MIGRATION.md` in this shape. Fill every bracket
from the analysis, name real files, and point each item at its section of
[breaking-changes.md](breaking-changes.md) instead of restating it. Leave out items that do not
apply. A stage that does not apply keeps its heading with `None: <why>`, so the stage numbers
stay: `execute-v2-migration` runs the stages by number, in this order.

```markdown
# Crossplane v2 migration plan: [project]

Generated: [date] · Function language(s): [per function] · Test language: [language]

## Overview

- XRDs [n] · compositions [n] · functions [n] · composition tests [n] · E2E tests [n] · examples [n]
- Breaking changes found: [each, with its breaking-changes.md section]
- Decisions: [Kind kept or renamed; deletionPolicy mapping; each non-default providerConfigRef;
  who reads the connection Secret] — [made by the user | assumed: why]
- Rollout risk: [installed v1 APIs, if the user has a control plane running this package]

Tick each item (`[x]`) when it is done. `execute-v2-migration` resumes at the first unticked one.

## Stage 1: Prepare

- [ ] Branch: `migrate-to-v2` checked out (`execute-v2-migration` pre-flight creates it if missing)
- [ ] `upbound.yaml`: `apiVersion: meta.dev.upbound.io/v2alpha1`
- [ ] Dependencies: [package: current → target version, from the dependency report]
- [ ] [If a function builds a Secret from typed models] `apiDependencies`: k8s `v1.33.0`
- [ ] `up dep update-cache && up project build` succeeds, and the generated models contain the
      `.m.` groups

## Stage 2: XRDs

### 2.[n] `apis/[path]/definition.yaml`

- [ ] `apiVersion: apiextensions.crossplane.io/v2`, `spec.scope: Namespaced`
- [ ] Remove [claimNames | connectionSecretKeys | defaultCompositeDeletePolicy]
- [ ] Kind: kept `[Kind]` [or: renamed to `[NewKind]` — new XRD name `[plural].[group]`; decision above]
- [ ] [deletionPolicy parameter] keep it; the function maps it (stage 5)
- [ ] [secret-reference parameter] `namespace` no longer required

## Stage 3: Compositions

### 3.[n] `apis/[path]/composition.yaml`

- [ ] [Remove `writeConnectionSecretsToNamespace`]
- [ ] [Kind renamed only] `compositeTypeRef.kind: [NewKind]`
- [ ] [`mode: Resources`] blocker: convert to a function pipeline first

## Stage 4: Examples

### 4.[n] `examples/[path].yaml`

- [ ] `metadata.namespace: [namespace]`
- [ ] [`compositionSelector` | `compositionRef` | …] under `spec.crossplane`
- [ ] [Remove `writeConnectionSecretToRef`]
- [ ] [Claim example] becomes an XR of `[Kind]`

## Stage 5: Tests, then functions

One block per function. Tests lead: update the function's tests to v2 first and see them fail
against the unmigrated function, then migrate the function until they pass.

### 5.[n] Function `functions/[name]` ([language]), covered by [tests]

- [ ] Tests (`author-tests`): [per test: XR namespace and `spec.crossplane`; expected
      `[group].m.[…]/[version]`; imports; connection Secret via `observedResources`, and
      `writeConnectionSecretToRef` on each resource it reads details from].
      `up test run "tests/[test]"` fails on [the v2 difference it should name]
- [ ] Function (`author-composition`): [imports → `.m.`; providerConfigRef: delete | keep
      `{kind: ClusterProviderConfig, name: [n]}`; deletionPolicy: delete | map the parameter;
      secret refs: drop `namespace`; connection Secret]. `up test run "tests/test-*"` passes
- [ ] [No test covers [behaviour]] prove it by mutation
      (`control-plane-project-charter/references/charter/tdd.md`)

### 5.[m] E2E test `tests/[e2etest-name]`

- [ ] (`author-tests`) namespaced XR manifests; the ProviderConfig it creates; Crossplane v2
      version if pinned

## Stage 6: Renames

[None: Kinds and directory names are kept.] Otherwise, only for a Kind renamed in stage 2:

- [ ] `git mv functions/[old] functions/[new]`; `functionRef.name` and `step` match
- [ ] `git mv tests/[old] tests/[new]`

## Stage 7: Verification

- [ ] `verify-configuration`: `up project build` and every composition test pass
- [ ] Render one example: no legacy provider group; managed resources carry `forProvider` only,
      unless the project's spec or API sets more
- [ ] E2E tests (`e2e-test-configuration`): create cloud resources, so only with the user's
      go-ahead; otherwise listed as not run

## Stage 8: Documentation

- [ ] README: API versions, namespaced example manifests, connection-secret changes, commands
- [ ] CI: Crossplane version; test paths if stage 6 renamed anything
```
