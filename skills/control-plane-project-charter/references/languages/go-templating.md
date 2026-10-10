# go-templating

Go templates with Sprig, used two ways in an `up` project: as **composition functions**
(`function-go-templating`) and as **tests**. They share a syntax and nothing else — different inputs, different
function sets — so do not carry idioms from one to the other unexamined.

The language-agnostic rules are in [`control-plane-project-charter`](../../SKILL.md).

| | |
|---|---|
| Scaffold a function | `up function generate <n> --language go-templating` → `functions/<n>/00-prelude.yaml.gotmpl`, `01-compose.yaml.gotmpl` |
| Scaffold a test | `up test generate <n> --language go-templating` → `tests/test-<n>/test.yaml.gotmpl` (with `--e2e`: `tests/e2etest-<n>/`) |
| Run tests | `up test run tests/test-<n>` |
| Provider fields | `.up/json/models/<reversed-group>-<version>-<Kind>.schema.json`, e.g. `io-upbound-m-aws-ec2-v1beta1-VPC.schema.json` (also `.up/go/models/io/upbound/m/aws/ec2/v1beta1/vpc.go`); CRD rules: [`../charter/provider-schema.md`](../charter/provider-schema.md) |

## Functions

`up` v0.55.0 builds a go-templating function on `function-go-templating-base:v0.9.0-13-gd1fa2e3`
(its `internal/language/images.yaml`). Everything below holds in function-go-templating v0.9.0 and
v0.13.0; the [upstream README](https://github.com/crossplane-contrib/function-go-templating#using-this-function)
on `main` also documents newer helpers. Everything the charter says about v2 managed resources (§5)
and test-first development (§3) applies.

**Layout.** `up function generate` writes `00-prelude.yaml.gotmpl` (`{{ $xr := getCompositeResource . }}`)
and `01-compose.yaml.gotmpl`. The function reads every file in lexical order, appends `---` to each,
and parses the result as one template named `manifests`: a variable set in the prelude is visible
in later files, and an error's `manifests:<line>` counts lines across the joined files. The
scaffold's commented example uses `s3.aws.upbound.io`, a v1 group; a v2 project needs the `.m.` groups.

**Input.** `.` is the `RunFunctionRequest` as JSON maps (`.observed.composite.resource`,
`.observed.resources.<name>.resource`, `.desired`, `.context`). An empty field is absent: until
something is observed, `.observed.resources` is nil.

| To | Write | What happens |
|---|---|---|
| read an observed composed resource | `{{ $vpc := getComposedResource . "vpc" }}` | the manifest, or nil; keyed by composition resource name, and never an error. `index .observed.resources "vpc"` fails with `index of untyped nil` while nothing is observed |
| read a field that may be missing | `{{ if $vpc.status.atProvider.id }}` | a missing key chains to no value without an error: falsy in `if`, `<no value>` when printed. `index` on an absent map errors: test the map first |
| compose a resource | `{{ setResourceNameAnnotation "vpc" }}` as a line under `metadata.annotations` | prints `gotemplating.fn.crossplane.io/composition-resource-name: vpc`; the function strips it and uses the value as the composition resource name. Any other document without it (not the XR, not a `meta.gotemplating…` kind) is a Fatal: `"<Kind>" template is missing required … annotation` |
| write XR status | a document with the XR's `apiVersion` and `kind`, a `status:`, and no resource-name annotation | merged into the desired XR's status; several such documents merge rather than replace. With the annotation it is composed as a resource instead |
| return a Fatal result | `{{ fail "message" }}` | any execution error returns Fatal `cannot execute template: …` before one document is decoded, so nothing the template printed is composed, wherever the `fail` sits |
| mark readiness | nothing: function-auto-ready decides. For what it cannot judge, `gotemplating.fn.crossplane.io/ready: "True"` | annotation values must be strings: an unquoted `True` is a Fatal `invalid annotations` |
| pass data to a later step | a document `apiVersion: meta.gotemplating.fn.crossplane.io/v1alpha1`, `kind: Context`, `data:` | pipeline context, not XR status |

**Functions available:** Sprig without `env` and `expandenv` (removed, unlike the test side), plus
`getCompositeResource`, `getComposedResource`, `getResourceCondition "Ready" (index .observed.resources
"<name>")` (the entry, not the manifest), `setResourceNameAnnotation`, `toYaml`, `fromYaml`,
`include`, `randomChoice`. No `required`. `getExtraResources` (v0.11.0) and
`getComposedConnectionDetails` (v0.13.0) are newer than the base.

**Go template traps:** `range $k := $map` binds the values; keys need `range $k, $v := $map`. A map
ranges in sorted key order, so iterate the XR's own list when its order matters.

**Testing a Fatal.** `up` has no unit-test tier for go-templating, and a CompositionTest cannot
assert a Fatal (author-tests, "A Fatal result"). A one-off `up test run` of a CompositionTest whose
input reaches the `fail` exits 1 and prints the message (observed, up v0.55.0):

```text
pipeline step "network" returned a fatal result: cannot execute template: template: manifests:38:21:
executing "manifests" at <fail (printf …)>: error calling fail: <your message>
```

That scratch test directory has to sit under `tests/`: `up test run` globs patterns relative to
the project's tests folder, so a path outside it prints `No test files found` and exits 0 (up
v0.55.0 source).

## Tests

### How `up` runs a go-templating test

Verified against `up` v0.55.0:

- A test directory is go-templating when **every** file in it ends in `.gotmpl` or `.tmpl`. One `README.md`
  next to the template and `up test run` stops with `No test files found`.
- All files in the directory are concatenated (lexical order, `---` between them) and rendered **once** with Go
  `text/template` plus [Sprig](https://masterminds.github.io/sprig/) — in-process, on your machine.
- **There is no input**: `.` is nil. The function-side helpers (`getCompositeResource` and friends) do not exist
  here, and neither do Helm's (`required`, `toYaml`, `include`): calling one fails with `function "…" not
  defined`. Sprig's `fail`, `hasKey`, `dict`, `list`, `toJson` are what you have.
- **No file access** either (no `readFile`): an `E2ETest`'s `manifests` can't read `examples/`, so inline the
  example XR. A `CompositionTest` doesn't need it: `xrPath` is a field of the emitted object, and `up` resolves
  it from the project root after the template has rendered (up v0.55.0 source), as for every test language.
- The output must be `items:` with a list of `CompositionTest` objects — the same object model as YAML tests
  ([`yaml.md`](yaml.md)).

Over plain YAML, templating buys a **test matrix**: one test body, ranged over a list of cases, with per-case
conditional expectations. If a test has no matrix, plain YAML is clearer — but match the language the project's
other tests use.

### Composition test template (`tests/test-<n>/test.yaml.gotmpl`)

Two cases of one input branch, each with an absence guard on the composite (`resourceRefs` is a list, and
lists match exactly), and a guard that turns a misspelt case key into a generation error:

```yaml
# code: language=yaml
# yaml-language-server: $schema=../../.up/json/models/test.schema.json
{{- $comp := "apis/buckets/composition.yaml" }}
{{- $xrd := "apis/buckets/definition.yaml" }}
{{- /* A misspelt key renders "<no value>" silently. "need" turns it into a generation error. */}}
{{- define "need" }}{{ range .keys }}{{ if not (hasKey $.case .) }}{{ fail (printf "test case %v: missing key %q" $.case . ) }}{{ end }}{{ end }}{{ end }}
{{- $cases := list
      (dict "name" "versioning-off" "versioning" false)
      (dict "name" "versioning-on" "versioning" true) }}
items:
{{- range $case := $cases }}
{{- template "need" (dict "case" $case "keys" (list "name" "versioning")) }}
- apiVersion: meta.dev.upbound.io/v1alpha1
  kind: CompositionTest
  metadata:
    name: tmpl-{{ $case.name }}
  spec:
    compositionPath: {{ $comp }}
    xrdPath: {{ $xrd }}
    timeoutSeconds: 120
    validate: false
    xr:
      apiVersion: demo.example.org/v1alpha1
      kind: Bucket
      metadata:
        name: example
        namespace: default
      spec:
        region: eu-central-1
        versioning: {{ $case.versioning }}
    assertResources:
    # The composite's resourceRefs is a list, and lists match exactly: a surplus composed resource fails here.
    # Names copied from render.log (up test run … --function-logs; renders are deterministic).
    - apiVersion: demo.example.org/v1alpha1
      kind: Bucket
      metadata:
        name: example
      spec:
        crossplane:
          resourceRefs:
{{- if $case.versioning }}
          - apiVersion: s3.aws.m.upbound.io/v1beta1
            kind: BucketVersioning
            name: example-41ed1f34c483
{{- end }}
          - apiVersion: s3.aws.m.upbound.io/v1beta1
            kind: Bucket
            name: example-963082b09556
    - apiVersion: s3.aws.m.upbound.io/v1beta1
      kind: Bucket
      metadata:
        annotations:
          crossplane.io/composition-resource-name: bucket
      spec:
        forProvider:
          region: eu-central-1
{{- if $case.versioning }}
    - apiVersion: s3.aws.m.upbound.io/v1beta1
      kind: BucketVersioning
      metadata:
        annotations:
          crossplane.io/composition-resource-name: versioning
      spec:
        forProvider:
          versioningConfiguration:
            status: Enabled
{{- end }}
{{- end }}
```

What the suite must contain beyond this — a minimal XR, one test per observed-state branch, every status field
asserted on the composite — is in
[`charter/evidence.md` § Coverage](../charter/evidence.md#coverage-what-the-suite-must-contain).
Observed-state tests add `observedResources` to a case exactly as in [`yaml.md`](yaml.md).

### Failure modes (reproduced)

| What you do | What happens |
|---|---|
| Misspell a case key (`$case.versionin`) | **silently renders `<no value>`** into the manifest. In the reproduction the XR got `versioning: <no value>`, the function read it as false, and the test passed for the wrong reason. Guard keys with `hasKey` + `fail` as above, and never let `<no value>` reach a manifest |
| Template syntax error / unknown function | the **whole run** fails at generation (`failed to parse templates`) |
| A non-template file in the test directory | nothing runs: `No test files found`, exit 0 |
| Expectation with the wrong shape (a list where the API has an object) | **passes** if the function writes the same wrong shape: assertions compare test against render, never against the CRD. Check field shapes in the provider's CRD (or the generated models) before writing them into a template |
| Expectation indented one level off | the assertion silently moves to another field or object; read the rendered manifest back if a test passes that should not |

**Indentation is the other trap.** A value that is itself a structure is safest as `{{ toJson $v }}` on one
line (JSON is valid YAML), and `{{-` / `-}}` trimming decides whether a block lands where you think. When a
template change makes a test pass or fail unexpectedly, render the template alone and read the YAML before
changing the expectation.

### E2E tests

`--e2e` scaffolds the same shape around an `E2ETest`; its fields and credentials are in author-tests' `e2e.md`
reference. Run-scoped values come from Sprig's `env` (the template renders locally, inside `up`):
`{{ env "UP_RUN_ID" }}`. Guard each with `{{ if not (env "X") }}{{ fail "X unset" }}{{ end }}` so a missing
value fails before a control plane is created. That `fail` also fires under a plain `up test run "tests/*"`,
so the composition gate is `up test run "tests/test-*"` (charter §7).
