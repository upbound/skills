# Reading a render, and making a suite exhaustive

What a clean `up project build` checks per language, how to find what a function emitted, how `assertResources` matches, the one assertion that catches a surplus resource, and what a suite must contain. [`control-plane-project-charter` §8](../../SKILL.md#8-a-green-run-is-not-evidence) states the rule.

## What a clean `up project build` checks

The package was assembled; a clean build never proves the function *runs*. Per language:

- **KCL and single-file Python:** nothing is imported, type-checked or executed — a function
  with an `AttributeError` on its normal path builds cleanly.
- **Python SDK layout:** the builder runs `hatch build` + `pip install`, so packaging and
  dependency errors fail, but `fn.py` is still never imported.
- **Go:** the build runs `go mod tidy` and a real compile, so a Go function that does not
  compile fails here.

## Reading the render

To find what a function emitted, read the render, not the assertions:

```bash
up test run "tests/<t>" --function-logs
# the run prints: Test artifacts written to <dir>
grep -h "composition-resource-name:" <dir>/*/render.log | sort
```

Three things about that path:

- **`--function-logs` is what writes the artifacts.** `--output-dir` alone writes nothing; it
  only changes the base directory. `--function-logs` is rejected outright with `--e2e`. A
  plain `up test run` writes no `_output/composition_test/<ts>/`, so any directory already
  there is stale: re-run with `--function-logs` before reading `render.log`.
- **Do not construct the path.** The directory carries a `YYYYMMDD-HHMMSS` timestamp you cannot
  know in advance; the run prints it.
- **One test *directory* produces one subdirectory per `CompositionTest`**, named for the
  object's `metadata.name`, not the directory's. `tests/test-storagebucket/` with two tests
  yields `test-storagebucket-bucket-created/` and `test-storagebucket-bucket-not-yet-created/`.
  Glob the run directory; don't guess a name.

That lists every resource the function produced, including the ones nothing asserts; `uniq -c`
adds nothing, since every name is unique. A new resource is untested until it is named in an
assertion.

`--debug` also prints each test's render to stderr once the run ends, with or without
`--function-logs` (which adds the function logs), and writes no directory. It is a `test run` flag:
`up --debug test run` fails with `unknown flag`. Its help marks it insecure: debug output can carry
tokens.

To render one XR without a test, from the project root:
`up composition render apis/<plural>/composition.yaml <xr.yaml> --xrd apis/<plural>/definition.yaml`.
Every file it takes, the XR included, is read relative to the project directory, so one outside
it is not found (up v0.55.0).

## How `assertResources` matches, and how to make a suite exhaustive

An expected resource is matched on **`apiVersion` + `kind` + `metadata.name`, plus every
annotation the expectation names** (up v0.55.0 source). For the name:

- **Your function sets it:** assert it.
- **Crossplane generates it, and the kind appears once in the render:** omit `metadata.name`.
  An omitted name matches whatever was rendered.
- **Crossplane generates it, and the kind appears more than once:** assert each one by the name
  copied from the render, or omit the name and assert its `crossplane.io/composition-resource-name`
  annotation, so each expectation matches exactly one resource. The annotation is the key your
  function stores the resource under, so that expectation can be written before the first render.

**A generated name can't be written before its resource renders.** The renderer's uid is
internal, so don't derive the hash, and don't predict the `resourceRefs` order either: observed
with up v0.55.0, it is sorted by `apiVersion`+`kind`+`name`, not by composition order. For a new
resource, RED is an expectation without `metadata.name` (`no actual resource found: …/<Kind>/`),
or a `resourceRefs` list one entry short. After GREEN, copy any names you assert, and the whole
`resourceRefs` list in its rendered order, from `render.log`.

**A generated name copied from a render is stable in a render.** §5's warning that generated
names change across re-creations is about a live control plane, where the XR's uid is real. A
render has no live XR, so the renderer synthesizes a deterministic uid, measured identical
across repeated runs, and the composed names are identical too (`example-2a20761a185a` on
every run).

Renaming the XR or a composition resource changes every generated name. That is correct:
renaming a composition resource orphans resources on a live platform (author-composition's
`patterns.md`, "The composition key is an API"), and you want a test that says so. The converse
holds too: the same XR (apiVersion, kind, namespace, name) and composition resource name render
the same generated name in every suite, since the name is derived from nothing else (Crossplane
v2.3.1 source).

A failure to match reads as `no actual resource found: <group>/<version>/<Kind>/<name>`; a
trailing slash means the expectation named no name. Observed with up v0.55.0, an expectation
that names an annotation the resource lacks, or gives it another value, fails the same way, with
no field diff. Annotations the expectation doesn't name are ignored: an extra annotation never
breaks a match (Out of scope, below). Labels and every other field are compared only after the
match, and a mismatch there prints `* <path>: Invalid value`.

`assertResources` ignores what it does not list, so a *surplus* resource is invisible: a
function that composes a resource it should have skipped leaves the suite green. To close that,
assert the composite's **`spec.crossplane.resourceRefs`**. It is a list, and lists match
exactly in length and order, so an unexpected resource fails it:

```
* spec.crossplane.resourceRefs: Invalid value: [...]: lengths of slices don't match
```

It is the one assertion that catches a resource nothing else names. Its order is the
renderer's and is not part of any published contract: an upstream reordering breaks the
assertion loudly rather than letting a real surplus through, the safe direction.

**One exact `resourceRefs` assertion per input shape, not per case.** Give each distinct composed
set (the shipped example, the minimal XR, each branch that adds or drops a resource) one guard;
other cases of that shape, and sibling suites rendering it, leave it out. Every exact list
changes when a resource is added, so a guard in every case turns each new resource into an edit
of every suite. A function unit test that asserts the exact set of names (Go:
`languages/go/functions.md`, unit-test template) guards surplus resources too.

**That covers surplus resources, not absent fields.** `assertResources` has no absence
operator, so a composition test cannot assert "this field is not set", and searching the CLI
for one wastes time. Assert it in a unit test on the function's desired state, in
the function's own language, or confirm it once in `render.log` and report it as not asserted.

## Coverage: what the suite must contain

The scaffold generates **one** test, against **one** example XR, asserting **only** composed
resources. That suite is green over a function that crashes on a minimal XR, silently drops
status fields, and never runs its readiness branch. "The tests pass" is not a verification
claim until the suite covers these three shapes. Each language file shows them in its own
syntax (Python: `languages/python/tests.md`; Go: `languages/go/tests.md`; YAML:
`languages/yaml.md`).

**1. One test per input shape — including a minimal XR.** Use the inline `xr` field instead of
`xrPath`, setting only the XRD-required fields and omitting every optional one; you need no
second example file. Inline `xr` and `xrPath` are mutually exclusive, so a test helper that
takes `xrPath` needs an `xr` parameter, never both at once. This is where "the user wrote the
obvious minimal manifest" bugs live: the shipped example usually sets every optional field, so
the omitted branch never renders. An input the function rejects with a Fatal result is the
exception: no `CompositionTest` can assert it (author-tests, "A Fatal result").

Besides `xr`, the test takes these inline fields, all optional: `composition` and `xrd` (inline
instead of `*Path`), `extraResources`, `context`, and `functionCredentialsPath`.

**2. One test per observed-state branch.** Code gated on observed resources or on readiness
**never executes** when `observedResources` is empty — it is unexercised, not merely
unasserted. Supply the observed state explicitly:

- **Every observed resource needs the `crossplane.io/composition-resource-name` annotation.** It
  is the key that matches a mock to the composed resource the function stores under that name;
  without it the renderer rejects the whole test (`encountered composed resource without required
  "crossplane.io/composition-resource-name" annotation`).
- **For a namespaced XR, every mock also needs `metadata.namespace` set to the XR's namespace.**
  The renderer looks mocks up in the XR's namespace, so one without it is silently not observed:
  no error, the function sees no observed resources, and the test fails only on its own
  assertions, as if the function were wrong (observed with up v0.55.0).
- **The mock's `metadata.name` becomes the composed resource's name.** Any valid name is
  observed, and the render keeps it instead of generating one, in the resource and in the
  composite's `resourceRefs`; an invalid name fails the render. So in a mocked case, assert the
  mock's names. To keep them equal to an unmocked case's generated names, copy those from that
  case's `render.log` (above). Checking that the mock names appear in the render proves nothing:
  they always do (Crossplane v2.3.1 source, the renderer up v0.55.0 runs; observed).
- **Prove the mocks are used** with a case that fails when they are ignored: assert a value only
  an observed resource can supply, such as a status field copied from a mock. A case that
  expects empty or default status passes whether the mocks are observed or not.
- Without `status.conditions` the resource is observed but **not** ready, which is its own
  useful test case. Add `Ready` and `Synced` conditions with status `True` to drive the ready
  branch.

Two cases, *observed but not ready* and *observed and ready*, are what separate a readiness
check from an existence check in your assertions; with only the ready case, a function that
never checks readiness passes.

**3. Assert every `status` field the function writes, on the composite.** `assertResources`
matches the composite ([§8](../../SKILL.md#8-a-green-run-is-not-evidence)). Without this, a
status write that clobbers nested keys — writing the status more than once can drop all but the
last (Go: `languages/go/functions.md`, several status fields) — passes silently, and you blame
the provider.

**A conditional resource needs all three:**

1. A test for the omitted case asserting the resources that *should* be there. This catches
   crashes on that branch — the common failure — and is a real regression guard.
2. A **`resourceRefs` assertion on the composite** (above), which turns absence into a real
   automated guard: a surplus resource fails the list comparison.
3. A read of `render.log` confirming the conditional resource is absent, quoted in your
   summary — that is where you get the `resourceRefs` order from anyway.

Report it accurately. With a `resourceRefs` assertion: *"test 4 covers the
omitted-lifecycleRules branch; the composite's resourceRefs assertion fails if a lifecycle
resource appears."* Without one: *"absence was confirmed once by reading render.log and is not
asserted by the suite."* Never *"validates that no lifecycle resource is created"* unless
something actually fails when one is.

**Out of scope for any composition test.** Assertions are partial-positive, so a *stray*
field — an external-name annotation on a resource whose external name the provider assigns —
is never flagged. That class fails only on a live control plane.
