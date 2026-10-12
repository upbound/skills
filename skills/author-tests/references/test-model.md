# The test model, patterns and common mistakes (language-agnostic)

The object model, structuring patterns and mistakes that apply to Crossplane configuration tests in
every language. The syntax is in the charter's language files, indexed by
`control-plane-project-charter/references/languages/README.md`; writing an `E2ETest` is
[e2e.md](e2e.md).

- [The test object model](#the-test-object-model)
- [Patterns](#patterns)
- [Common mistakes](#common-mistakes)
  1. [Guessed composed-resource names](#1-guessed-composed-resource-names)
  2. [A composed resource with no assertion at all](#2-a-composed-resource-with-no-assertion-at-all)
  3. [Assuming you cannot assert the composite's own status](#3-assuming-you-cannot-assert-the-composites-own-status)
  4. [Partial for objects, exact for lists](#4-partial-for-objects-exact-for-lists--and-the-two-fail-differently)
  5. [Designing coverage without reading the XRD's defaults](#5-designing-coverage-without-reading-the-xrds-defaults)

---

## The test object model

Every test produces one of two objects under `apiVersion: meta.dev.upbound.io/v1alpha1`. KCL,
Python and Go builders and raw YAML all render to exactly this shape.

### CompositionTest (fast, local, no cloud)

| Field | Meaning |
|-------|---------|
| `metadata.name` | Test name (unique within its directory) |
| `spec.compositionPath` | Path to the composition under test (e.g. `apis/<xr>/composition.yaml`) |
| `spec.xrdPath` | Path to the XRD (`apis/<xr>/definition.yaml`); its defaults reach the render |
| `spec.xr` | The XR under test, defined **inline** (recommended). Some layouts use `xrPath` instead; the two are mutually exclusive |
| `spec.validate` | `false`, the scaffold default; leave it. `up test run` never reads it (up v0.55.0 source), so `true` checks nothing: an unknown field or a wrong type in a composed resource passes either way |
| `spec.timeoutSeconds` | **≥60** |
| `spec.assertResources` | Expected rendered resources. Assert the fields, not just existence. Matches the **composite** as well as composed resources ([mistake 3](#3-assuming-you-cannot-assert-the-composites-own-status)) |
| `spec.observedResources` | Optional. Pre-existing resources (with mocked `status`) fed into the render, to test dependency ordering and status-driven branches |

### E2ETest (real cloud lifecycle)

Fields, defaults, credentials, the ProviderConfig it creates, and what it cannot assert:
[e2e.md](e2e.md).

Managed resources in either kind follow binding rule 4; how the `.m.` group is spelled
(import path or `apiVersion` string) is in the language file.

---

## Patterns

Ways of *structuring* tests. Each language file shows the syntax.

### Resource-focused bundle

Group 3-5 related tests in one directory that share a base spec (composition/XRD path,
timeout, validate) and vary only the XR and the expected resources: basic, feature-enabled,
feature-disabled. Syntax: KCL spread, a Python helper, YAML `---` documents.

### Parameterized test matrix

With 5+ near-identical variants (one per flag, region or size), generate them from a data
list instead of copy-pasting. KCL, Python and Go build these programmatically; YAML lists them
out (fine, just verbose).

### Sequential testing with observedResources

Test resource **dependencies** and **status-driven branches** without a cloud, by feeding
`observedResources` with mocked `status` into the render:

- Test N asserts what renders given the observed state of prior resources.
- Keep `validate: false`, as in the table above.
- Mock only the status fields the composition reads (e.g. `status.atProvider.state: deployed`, a
  condition `type: Ready, status: "True"`, or a provider-specific contract like
  `status.eks.clusterArn`). What a mock needs to be observed at all (the annotation, and for a
  namespaced XR the XR's namespace), what its name does, and the condition rules:
  `control-plane-project-charter/references/charter/evidence.md`, "Coverage".

This verifies "resource B only renders once resource A is Ready" and "the XR surfaces field X once
the observed endpoint is known". Examples: the charter's language file for your test language (Go:
`control-plane-project-charter/references/languages/go/tests.md`, `status-from-observed-bucket`;
YAML: `control-plane-project-charter/references/languages/yaml.md`).

---

## Common mistakes

Language-neutral mistakes beyond the rules in SKILL.md. KCL import-syntax and Python
dump-mode mistakes live in their language files.

### 1. Guessed composed-resource names

**Wrong:** `name: test-vpc` (a guess).
**Right:** omit `metadata.name` when a kind appears once in the render; when it appears more
than once, assert each by the name copied from the render, which is deterministic there, or by
its `crossplane.io/composition-resource-name` annotation
(`control-plane-project-charter/references/charter/evidence.md`).

### 2. A composed resource with no assertion at all

`assertResources` ignores every resource it does not list (charter §8), so an extra managed resource
left a 2-test suite at 2/2 PASS. **Right:** assert every resource the composition can emit,
conditional ones in their own test; cross-check against the render and assert the composite's exact
`spec.crossplane.resourceRefs` (`control-plane-project-charter/references/charter/evidence.md`).

### 3. Assuming you cannot assert the composite's own `status`

`assertResources` is named for composed resources and typed
`Optional[List[Dict[str, Any]]]`, so it looks like it takes only composed resources.
**It matches the rendered composite too.** Drop the XR itself into `assertResources` with a
`status` block and composition outputs become testable.

**Wrong:** concluding "the CompositionTest model has no `assertComposite`/`assertStatus`
field, so composition outputs cannot be verified", and leaving `assertResources=[]` on the
test written to cover status propagation.
**Right:** assert the composite:
```python
assertResources=[
    {
        "apiVersion": "platform.example.com/v1alpha1",
        "kind": "EncryptedTable",
        "metadata": k8s.ObjectMeta(name="user-sessions", namespace="default")
                       .model_dump(by_alias=True, exclude_unset=True),
        "status": {"tableName": "user-sessions", "kmsKeyId": "1111-..."},
    },
]
```
Verified by mutating one expected value, which fails with an exact field path and a diff:
```text
* status.kmsKeyId: Invalid value: "1111-...": Expected value: "MY-OWN-DELIBERATE-MUTATION"
--- expected
+++ actual
-  kmsKeyId: MY-OWN-DELIBERATE-MUTATION
+  kmsKeyId: 1111-...
```
Any XR whose `status` is populated from observed resources needs this — it is the only
programmatic check on composition outputs.

### 4. Partial for objects, exact for lists — and the two fail differently

Charter §8: an asserted object is partial at every depth (the surplus is never reported); an
asserted list must match exactly, in length and order (`lengths of slices don't match`).
**Right:** assert a whole list, in order. An exact key set on a mapping is not expressible in
`assertResources`: read it from the render, and say which of the two claims you made.

### 5. Designing coverage without reading the XRD's defaults

A test's input is not the XR you wrote but the XR **after the XRD's defaults have been
applied**. A field you omitted to exercise the "unset" branch is not unset if the XRD gives it
a `default`, and the branch you meant to cover never runs.

Read the XRD before choosing the shapes to test:

```bash
yq '.spec.versions[].schema.openAPIV3Schema.properties.spec' apis/<kind>/definition.yaml \
  | grep -nE 'default:|required:|enum:'
```

**Wrong:** "The minimal XR omits `retentionDays`, so this test covers the no-retention branch."
**Right:** check first. If the XRD defaults `retentionDays: 30`, no XR can omit it, that branch
is unreachable from the API, and the honest coverage note says so — or the default is the bug.

A `default:` on an array of objects behaves the same: an XR that omits the field gets the whole
default list in the render, and an explicit `[]` is kept, not replaced (observed with up v0.55.0).
