---
name: author-composition
description: Use this skill when the user asks to create, extend, modify, or debug a Crossplane composition function in a control-plane project — in any language (KCL, Python, TypeScript, Go, go-templating). Detects the function language and applies the matching reference. Also use when asked about Crossplane v2 composition patterns, model/type import paths, namespaced `.m.` APIs, or why a composition renders green but the resource never reconciles. For authoring the tests themselves use author-tests; for XRD design use author-configuration-package. Always load this skill before writing or changing composition function code, instead of writing it directly - also when you get there partway through another skill's workflow, such as scaffolding a new package. It enforces the v2 rules that composition tests cannot catch — `forProvider`-only resources, no dangling `providerConfigRef`, resolved import paths — and the test-first loop that makes a coverage claim checkable.
license: Apache-2.0
references:
  - references/patterns.md
---

# Composition Authoring

Author and modify Crossplane composition functions, in KCL, Python, Go,
go-templating or (by hand) TypeScript, test first.

## First: load the charter

If `control-plane-project-charter` is not loaded in this session, load it now, before you
follow any link or phase below (or read the `SKILL.md` in its directory, beside this one).
Loading this skill does not load it, and the rules here cite its sections (§1–§10) and files.

## Before you start

A composition's *meaning* is language-agnostic; only its *syntax* differs. Read three layers:
the charter (the rules), [patterns.md](references/patterns.md) (what each pattern means), and
your language's file under `control-plane-project-charter/references/languages/` (the
syntax).

- **Reviewing function code:** the checks are in
  `control-plane-project-charter/references/charter/review.md`. **A test passes but the resource
  misbehaves on a control plane:**
  [patterns.md](references/patterns.md#a-green-test-with-a-misbehaving-resource).
- Tests → `author-tests`; XRD design and scaffolding → `author-configuration-package`; the
  gate and deploying → `verify-configuration`; live cloud runs → `e2e-test-configuration`;
  migrating a function to v2 → `plan-v2-migration` (the function-side points:
  [patterns.md](references/patterns.md#migrating-a-function-to-v2)).

## Binding rules — they hold even if you open nothing else

The project's own API, design or gate script wins over these: say where you departed.

1. **Never block on a question nobody can answer.** Interactive, ask only what the project
   can't tell you; unattended, never ask: decide from the spec and state the assumption, or
   stop and report (charter §1).
2. **Never create a group, Space, control plane or cloud resource as a side effect, and never
   pass `--public` yourself** (§9). Run `up test run --e2e` only after loading
   e2e-test-configuration: it has each target's preconditions, and the read-back and teardown
   rules.
3. **Test first: watch each new composition or unit test fail for the reason you intended**;
   for a new E2ETest this is optional. A syntax error, a missing path, `✗ Parsing tests`, a
   compile error or a bug in the test's own logic is a broken test, not RED. Backfill by
   mutating the implementation, never the expected value; a surviving mutant of your change
   is a missing test (§3).
4. **In a v2 project, managed resources carry `forProvider` only**, on the `.m.` API groups,
   unless the project's spec or API sets more: no `deletionPolicy`, `managementPolicies` or
   `metadata.namespace`; omit `providerConfigRef` if and only if `ClusterProviderConfig/default`
   exists and is the right one. One whose connection details the function reads also needs
   `writeConnectionSecretToRef`, and a missing detail never falls back to a value. A v1 project
   stays v1 (§5).
5. **Claim only what ran:** the command's own exit code, not `tail`'s: redirect, then read
   `$?` (`cmd > /tmp/x.log 2>&1; echo "exit=$?"`); after a pipe, bash `${PIPESTATUS[0]}`,
   zsh `$pipestatus[1]`. `No test files found` means nothing ran. Name the layer you reached —
   render, composition test, local control plane, cloud — and never claim one you did not
   reach; for each new composition or unit test, the change that turns it red. Comments and
   docs claim no more (§4, §8).

## Phase 1: Detect the language and the Crossplane generation — do not ask

**Language:** detect it as charter §10 says. If they are not open in this session, open its
index and function file in `control-plane-project-charter/references/languages/` now, before
you write or change a line, even in a project that already has code (Go: `go.md`, `go/functions.md`; Python: `python.md`, `python/patterns.md`; KCL: `kcl.md`,
`kcl/patterns.md`; go-templating and YAML: their one file): its
layout, imports and bootstrap are wrong by default if you guess. No functions yet: take it
from `upbound.yaml`, else an existing function, else as
`control-plane-project-charter/references/languages/README.md` says (and when to add a step in
another language).

**Generation**, which governs more of the guidance than the language does:

```
apis/*/definition.yaml: apiextensions.crossplane.io/v2  → v2: binding rule 4 and charter §5 apply
                                                   /v1  → v1: they do not
```

A v1 project uses the non-`.m.` models and a cluster-scoped `ProviderConfig`, and its shipped
function breaks every v2 rule.

## Phase 2: Discover — do not ask

Make sure the XRD and a composition exist: the test points at them. Write the XRD yourself
(`author-configuration-package`;
`control-plane-project-charter/references/charter/v2-resources.md` has the v2 skeleton).
Scaffold the composition with `up composition generate`, which does not wire in your function
(`control-plane-project-charter/references/charter/generators.md`), and wire it in with
`up function generate <n> <composition-path> --language <lang>` (Phase 1). Leave the function body empty or unchanged.

`control-plane-project-charter` §2 has the general table. The composition-specific additions:

| What you need | How to get it — no question required |
|---|---|
| **Models missing** (fresh clone, or only your XR's model missing) | `.up/` is gitignored. Run `up project build`. It resolves and caches the dependencies itself and writes every model, your XR's included (observed with up v0.55.0, with an empty `--cache-dir` and no `.up/`). `up dep update-cache` refreshes only the dependency models |
| Function layout, import line, class names, field names and types | the generated models, where and how the language file says (Go: `control-plane-project-charter/references/languages/go.md`, "Imports and models") |

**Python:** before Phase 3, run what
`control-plane-project-charter/references/languages/python.md` says with this skill's
[`scripts/`](scripts/): `scripts/setup_venv.py` and `scripts/probe_project.py` (layout,
imports, fields, generation).

**Never hand-derive an import path and never guess a provider field name.** Both are one
command away.

Worth asking, and only if `args` does not already say: optional/conditional resources, whether
connection details must reach the XR, and whether child XRs are composed. If unstated, choose
the simplest correct behaviour, say so in your summary, and continue.

## Phase 3: Design against what you discovered

[patterns.md](references/patterns.md) has each design question in full. In brief:

1. **Layout** — match what the project already uses; never convert one to the other.
2. **Composition keys** — they become `crossplane.io/composition-resource-name`, and
   Crossplane derives resource names from them. A rename, like a removed resource, deletes the
   live one: a migration.
3. **References before status plumbing.** If resource B needs an ARN or ID from resource A,
   a `*Ref` field makes the provider resolve it, so the composition stays single-pass and
   never reads A's status.
4. **List fields.** *One element → one resource* is a decision you justify, not a default
   (charter §6).
5. **Conditional resources** — which use `ready OR exists`, and where each belongs relative to
   the existing guard clauses (patterns.md: the guard-clause chain).
6. **Flexible maps** — tags and labels need `additionalProperties` in the XRD; fixed
   `properties:` produce null-value failures in typed languages.
7. **Split by concern as the function grows.** Keep the entry point (`RunFunction`) to the
   orchestration, and give resource builders, rendered documents (e.g. JSON policies) and status
   their own files in the same package; split the unit tests the same way. One file of many
   hundred lines is hard to review, maintain and extend.

## Phase 4: RED — write the failing test before the implementation

Binding rule 3, before any function code; charter §3 owns the loop. Write what the design
fixes — keys, Kinds, fields — as an assertion now, while it states intent.

**Who does what in a run that changes the function.** `author-tests` writes the test (its
Phases 1–4, Phase 2 for what no render reaches). This skill runs RED (below), GREEN
(Phase 5) and REFACTOR (Phase 6). The gate comes once, after this skill's Phase 6, as
`author-tests` Phase 6 describes. A run that only adds or changes tests stays in `author-tests`
throughout.

Run `up test run "tests/<t>"` and keep the failure text; the reason must be one charter §3's
table counts as RED. Adding to a composition that already works: confirm the new assertion
fails while the others pass.

## Phase 5: GREEN — implement until the test passes

Implement until the test passes, and no further. Re-run `up test run "tests/<t>"` and report
the RED→GREEN transition, not only the final green.

Not open yet in this session? Open the language's index and function file now (Phase 1 names
them): they have the bootstrap, the syntax and the failure modes. Language-independent, in order:

1. Parse the observed XR with the language's required bootstrap (Python needs
   `struct_to_dict`; skipping it fails at model construction (`AttributeError: get`). Go: the
   generated models are not `runtime.Object`s, so convert through JSON, in and out).
2. Create managed resources per binding rule 4.
3. Convert flexible maps to the language's plain map type before assigning them.
4. Extract connection details by **composition key**, not by resource name; open
   `control-plane-project-charter/references/charter/v2-resources.md#connection-details-reach-a-function-only-through-writeconnectionsecrettoref`
   now.
5. Mark a composed ProviderConfig — anything auto-ready cannot judge — ready explicitly.
6. Give each optional resource its **own conditional block** rather than another early
   return (patterns.md: the guard-clause chain).
7. Before you write XR status or conditions, open
   `control-plane-project-charter/references/charter/v2-resources.md#what-the-function-returns-for-the-xr`
   now.

For iterating on a crash rather than an assertion, use the fast tier where the language
offers one (Python: `unittest` in `functions/<n>/tests/`; Go: `go test ./...` in
`functions/<n>/` — the scaffold's `fn_test.go` is an empty table that passes with zero cases,
so add one before you count it). It supplements the loop and never replaces it.

## Phase 6: REFACTOR and verify — coverage, not a green exit code

With the suite green, tidy the implementation, then add the next failing assertion and
repeat. Before you call anything covered (charter §8):

1. **Check provider validity**, not only v2 conformance, as charter §6 says; write the result
   in your summary.
2. **Grep your own function** with the two greps in
   `control-plane-project-charter/references/charter/v2-resources.md#grep-your-own-function-before-you-report`
   and judge each hit rather
   than counting them. Legitimate: a `namespace` chosen by a cluster-scoped XR or set on an
   object embedded inside `forProvider` (a provider-kubernetes `Object` manifest); a
   `providerConfigRef` where the right config is not `ClusterProviderConfig/default`, with a
   `kind` naming an object that exists; any field the project's spec or API sets. A `namespace`
   on a composed Secret or ConfigMap of a namespaced XR is not legitimate: Crossplane overwrites
   it.
3. **Read the render, not the assertions:** `up test run "tests/test-*" --function-logs`, then
   open `control-plane-project-charter/references/charter/evidence.md#reading-the-render` now
   and read the render as it says (the directory the run prints as
   `Test artifacts written to <dir>`). A run without the flag writes nothing,
   and any existing directory is stale. Add each emitted resource to `assertResources`; until you
   do, it is untested even though the suite is green.
4. **The suite satisfies
   `control-plane-project-charter/references/charter/evidence.md#coverage-what-the-suite-must-contain`**:
   each input shape including a minimal XR, each observed-state branch, every `status` field on
   the composite.

## Phase 7: Report

**Claim only what ran** (binding rule 5, charter §4). Composition tests render and assert;
they talk to no provider and install nothing, so never "production-ready", "deployable" or
"verified".

**Out of reach locally:** external-name semantics — whether a resource's external name is
provider-assigned or the identifier you set — are undiscoverable from CRDs or models. Check it
on a live control plane, or say it is unchecked.

## Success criteria

Checks for you before you report, not a report format (`control-plane-project-charter` §4).

1. The function language and generation were detected, not assumed, and the matching
   `languages/` file was read
2. Import paths resolved from the project, never derived by hand
3. Managed resources follow binding rule 4, with no dangling `providerConfigRef`
4. A test was written first, run, and observed to fail for the right reason
5. The RED→GREEN transition is reported, with the failure text
6. The render was read and every emitted resource is asserted
7. Provider-level constraints were checked, and the result — including "found nothing" —
   is in the summary
8. The summary claims the layer that was actually reached, and no further
