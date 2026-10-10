# Reviewing a change

The Crossplane-specific checks for reviewing a change to a control-plane project — function
code, tests, the package — beyond reading the diff. The rules behind them are the charter's
([`control-plane-project-charter`](../../SKILL.md), cited as §N).

## Re-run the gate and read its output

- Run the project's own gate if it has one, else `up project build` and
  `up test run "tests/test-*" > /tmp/t.log 2>&1; echo "exit=$?"`. Read the log, not only the
  exit code: after a `| tail`, `$?` is `tail`'s (§4).
- `No test files found`, or a test program printing `items: []`, is zero tests, though it exits
  0. A vacuous green is not a pass (§8).
- A run that stops at `✗ Parsing tests` is a broken test, not a failing one, and never RED:
  an e2e program missing an input under a `tests/*` glob (§7), or a test program turned linter
  (below).
- To re-run an `E2ETest`, load e2e-test-configuration and follow its Phase 2: on kind, the
  default umask (`022`); `UP_<CLOUD>_CREDENTIALS` holds the credentials text, never a path to a
  file. Check or diff an e2e program's output only with a dummy value (author-tests' `e2e.md`).

## Each new test bites

- For each new test, the report names the implementation change that turns it red and says it
  was seen failing. An `E2ETest` may instead be reported unproven (§3, §4).
- **Check one yourself:** mutate the implementation (delete the field, move the block below an
  early return), confirm that exactly that test goes red, then revert with git, after keeping
  any uncommitted change in that file: the revert discards it
  ([`tdd.md`](tdd.md#backfilling-tests-for-code-that-already-exists)). A RED produced by editing
  the expected value does not count, and neither does a syntax error, a missing path or a
  compile error (§3).
- Every value the function passes through has, in at least one test, an input that is neither
  its default nor shared with a sibling field. Otherwise a hard-coded constant stays green (§3).
- An entry naming only `kind` passes against any resource of that kind: the fields the change
  adds are asserted, and every `status` field the function writes is asserted on the composite.
- No test program for a declarative file (the XRD surface, `examples/`, an MRAP,
  `upbound.yaml`; §3). A program under `tests/` that checks repo files and exits non-zero is a
  linter, not a test: it adds zero tests and, failing, stops the run at `✗ Parsing tests`. What
  no render reaches is covered by the build or reported uncovered (author-tests, "Checking what is not a render").
- An `E2ETest` that differs from another only in its name covers nothing new and doubles the
  cloud run (author-tests' `e2e.md`).

## Read the render

```bash
up test run "tests/<t>" --function-logs
# the run prints: Test artifacts written to <dir>
grep -h "composition-resource-name:" <dir>/*/render.log | sort
```

A plain `up test run` writes no artifacts: read only the directory your own `--function-logs` run
printed; one already under `_output/composition_test/` is another run's
([`evidence.md`](evidence.md#reading-the-render)).

Every resource the change produces is in the render and asserted. A resource in the render that
no test names is untested, though the suite is green; only an exact
`spec.crossplane.resourceRefs` assertion fails on a surplus one ([`evidence.md`](evidence.md),
"How `assertResources` matches" and "Coverage": named annotations only, stray fields never
flagged, what a mock needs).

## Function code

- The language's required bootstrap is present where the language file names one (Python:
  `python/patterns.md`, "Function bootstrap"; TypeScript: `src/main.ts`; go-templating: the
  scaffold's `00-prelude.yaml.gotmpl`).
- Imports resolve against the generated models, never a hand-derived path, and use the `.m.`
  groups in a v2 project. A v1 project stays v1 (§5).
- Flexible maps (tags, labels) are converted to the language's plain map type.
- Guard-clause order: a return above the new resource does not gate it unintentionally.
- A composed ProviderConfig, or anything else auto-ready cannot judge, is marked ready
  explicitly.

## The v2 fields

Run the two greps under "Grep your own function before you report" in
[`v2-resources.md`](v2-resources.md) and judge each hit; "no output" is not the pass condition.

- Flag `providerConfigRef`, `managementPolicies` or an MR's `metadata.namespace` as removable
  **unless the project's spec or API sets them**. Flag `deletionPolicy` on a namespaced MR: the
  field does not exist (§5).
- Flag `providerConfigRef.kind: ProviderConfig` as a bug only when no namespaced
  `ProviderConfig` of that name exists in, or is created in, the XR's namespace.
- A Kubernetes object embedded in `forProvider`, such as a provider-kubernetes `Object`
  manifest, needs its own `metadata.namespace`; a missing one is a bug the composition tests
  miss. A namespace set on a composed resource of a namespaced XR is overwritten by Crossplane.
- A function that reads a composed resource's connection details sets
  `writeConnectionSecretToRef` on that resource, and composes nothing from a missing value: a
  fallback such as `or ""` is a bug no render shows
  ([`v2-resources.md`](v2-resources.md#connection-details-reach-a-function-only-through-writeconnectionsecrettoref)).

## Provider constraints and dependencies

- The report says which Kinds were checked against the provider schema and the cloud API's own
  rules, and what could not be confirmed. Silently skipping is a finding (§6; the CRD's
  `x-kubernetes-validations`: [`provider-schema.md`](provider-schema.md)).
- Flag an unbounded dependency: a `dependsOn` `version` with no cap on the major, such as the
  `'>=v0.0.0'` a bare `up dep add <ref>` or `up composition generate` writes
  (author-configuration-package).
- An external pipeline function missing from `dependsOn` fails every render with
  `unknown function`; so does an embedded function's `functionRef.name` that departs from
  [`generators.md`](generators.md)'s formula.

## What the report claims

- The report names the layer reached — render, composition test, local control plane, cloud —
  and claims nothing beyond it. A local kind run is not a Space result (§4, §8, §9).
- Comments, docs and READMEs claim no more than a named test or run (§4).
