# Go: composition functions

Imports and the `go.mod` wiring are in [`../go.md`](../go.md#imports-and-models). The models are on
disk under `.up/go/models/io/upbound/m/<provider>/<service>/<version>/<kind>.go` (no `dev.upbound.io`
level). What a v2 managed resource needs is in
[`control-plane-project-charter` §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs).

The scaffold facts below were observed on `up` v0.55.0, which pins `function-sdk-go` v0.5.0; every SDK name
was checked against that version's source. The function template passes the three tests in
[`tests.md`](tests.md) under `up test run`, and the mutant `if versioning` → `if true` turns
`versioning-disabled` red. The unit-test template goes red under the same mutant.

## The scaffold, and what to change in it

`up function generate <n> <composition-path> --language go` writes `functions/<n>/`:

| File | What it is | What to do |
|---|---|---|
| `main.go` | the gRPC server (`function.Serve`, kong flags) | leave it alone |
| `fn.go` | `RunFunction`: `response.To(...)`, a TODO, and a `FunctionSuccess` condition with `.TargetCompositeAndClaim()` | write the logic. Replace `.TargetCompositeAndClaim()` with `.TargetComposite()`: it is a v1 leftover, and a v2 namespaced XR has no claim |
| `fn_test.go` | `TestRunFunction` with an **empty `cases` table** | add cases before you trust it. As generated, `go test` prints `ok` and runs nothing, the same vacuous pass as the stub test in charter §8 |
| `go.mod` | `function-sdk-go v0.5.0`, plus the models `require` and `replace` | keep the `replace` ([`../go.md`](../go.md#gomod-the-models-replace)) |

Compile with `go vet ./...` or `go build -o /dev/null ./...`, never plain `go build ./...` (Failure modes,
below), and gitignore `functions/<n>/<n>`.

## function-sdk-go v0.5: the calls a composition needs

| Call | What it gives you |
|---|---|
| `response.To(req, response.DefaultTTL)` | the response, already carrying the desired state earlier pipeline steps produced. Start with it |
| `request.GetObservedCompositeResource(req)` | `*resource.Composite`; `.Resource` is unstructured (`GetString("spec.region")`). Convert it into your XR model for typed access |
| `request.GetDesiredComposedResources(req)` | `map[resource.Name]*resource.DesiredComposed`, what earlier steps composed. Add yours to it |
| `response.SetDesiredComposedResources(rsp, desired)` | writes the map into `rsp`, keyed by composition resource name. Crossplane turns each key into the `crossplane.io/composition-resource-name` annotation at render, so a unit test sees the map key, not the annotation (unit-test template, below). It sets keys and never removes one |
| `request.GetObservedComposedResources(req)` | `map[resource.Name]resource.ObservedComposed`, keyed by composition resource name: `observed["bucket"].Resource.GetString("status.atProvider.arn")` |
| `.Resource.GetAnnotations()["crossplane.io/external-name"]` | an annotation. Its key has dots, so the path `metadata.annotations.crossplane.io/…` fails with `no such field`; `GetStringObject("metadata.annotations")[key]` and the bracket path `GetString("metadata.annotations[<key>]")` work too |
| `.Resource.SetValue("metadata.labels[<key>]", v)` | writes one label whose key has dots or slashes; the same bracket segment works for `metadata.annotations[<key>]` and `spec.forProvider.tags[<key>]` (used in a passing v0.5.0 function). `SetLabels`/`SetAnnotations`, from the embedded Kubernetes `Unstructured`, replace the whole map: read it with `GetLabels()`, add the key, write it back |
| `request.GetDesiredCompositeResource(req)` + `response.SetDesiredCompositeResource(rsp, dxr)` | XR status: `dxr.Resource.SetString("status.bucketArn", arn)` between the two; lists and objects with `SetValue("status.subnetIds", []any{…})`. `composed.Unstructured` has the same `SetValue`; there is no `SetNestedField`. Several fields: one pair per run ([below](#several-status-fields)) |
| `response.Fatal(rsp, err)`, then `return rsp, nil` | how a function reports an error: as a fatal result in the response, not as Go's `error` |
| `response.ConditionTrue(rsp, typ, reason).TargetComposite()` | a condition on the XR |

**The generated models are not `runtime.Object`s.** They have no `DeepCopyObject`, so `composed.From(model)`
and `resource.AsStruct(model)` do not compile with one (`does not implement runtime.Object (missing method
DeepCopyObject)`). Round-trip through JSON instead: `composed.New()`, then `json.Marshal` the model and
`json.Unmarshal` into it. That is `convertViaJSON` in the template. Every model field is a pointer with
`omitempty`, so only the fields you set are emitted.

**Where things are in v0.5.0** (`github.com/crossplane/function-sdk-go/…`): `request` and `response` (the calls
above); `resource` (`Composite`, `DesiredComposed`, `ObservedComposed`, `Name`, `AsObject`, `AsStruct`);
`resource/composed` and `resource/composite` (each package's `Unstructured` with its `Get*`/`Set*` methods);
`errors`; `logging`; `proto/v1` (`fnv1`). Field paths are crossplane-runtime's `v2/pkg/fieldpath`. There is no
`resource/unstructured.go` or `resource/convert.go`, and no `crossplane-runtime/v2/pkg/resource/errors`.

## Function template (`functions/<n>/fn.go`)

The function the [`tests.md`](tests.md) template tests: a Bucket, a BucketVersioning when `spec.versioning`
is true, and `status.bucketArn` from the observed bucket. Keep the shape; replace the resources.

Leave `DesiredComposed.Ready` unset unless the project says otherwise; a function-auto-ready step later in the
pipeline marks readiness.

```go
package main

import (
	"context"
	"encoding/json"

	"k8s.io/utils/ptr"

	"github.com/crossplane/function-sdk-go/errors"
	"github.com/crossplane/function-sdk-go/logging"
	fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
	"github.com/crossplane/function-sdk-go/request"
	"github.com/crossplane/function-sdk-go/resource"
	"github.com/crossplane/function-sdk-go/resource/composed"
	"github.com/crossplane/function-sdk-go/response"

	s3v1beta1 "dev.upbound.io/models/io/upbound/m/aws/s3/v1beta1" // .m. = namespaced (v2)
	xrv1alpha1 "dev.upbound.io/models/org/example/demo/v1alpha1"  // your XR: group demo.example.org, reversed
)

// Function is your composition function.
type Function struct {
	fnv1.UnimplementedFunctionRunnerServiceServer

	log logging.Logger
}

// RunFunction composes a Bucket, a BucketVersioning when spec.versioning is
// true, and copies the bucket's ARN to the XR's status once it is observed.
func (f *Function) RunFunction(_ context.Context, req *fnv1.RunFunctionRequest) (*fnv1.RunFunctionResponse, error) {
	f.log.Info("Running function", "tag", req.GetMeta().GetTag())
	rsp := response.To(req, response.DefaultTTL) // carries the desired state earlier steps produced

	oxr, err := request.GetObservedCompositeResource(req)
	if err != nil {
		response.Fatal(rsp, errors.Wrap(err, "cannot get observed composite resource"))
		return rsp, nil // report errors as a Fatal result, not as the Go error
	}
	var xr xrv1alpha1.Bucket
	if err := convertViaJSON(&xr, oxr.Resource); err != nil {
		response.Fatal(rsp, errors.Wrap(err, "cannot convert composite resource"))
		return rsp, nil
	}
	if xr.Spec == nil || xr.Spec.Region == nil {
		response.Fatal(rsp, errors.New("spec.region is required"))
		return rsp, nil
	}

	desired, err := request.GetDesiredComposedResources(req)
	if err != nil {
		response.Fatal(rsp, errors.Wrap(err, "cannot get desired composed resources"))
		return rsp, nil
	}

	bucket := &s3v1beta1.Bucket{
		APIVersion: ptr.To(s3v1beta1.BucketAPIVersions3AwsMUpboundIoV1Beta1),
		Kind:       ptr.To(s3v1beta1.BucketKindBucket),
		Spec: &s3v1beta1.BucketSpec{
			ForProvider: &s3v1beta1.BucketSpecForProvider{Region: xr.Spec.Region},
		},
	}
	if err := addDesired(desired, "bucket", bucket); err != nil {
		response.Fatal(rsp, err)
		return rsp, nil
	}

	if ptr.Deref(xr.Spec.Versioning, false) {
		versioning := &s3v1beta1.BucketVersioning{
			APIVersion: ptr.To(s3v1beta1.BucketVersioningAPIVersions3AwsMUpboundIoV1Beta1),
			Kind:       ptr.To(s3v1beta1.BucketVersioningKindBucketVersioning),
			Spec: &s3v1beta1.BucketVersioningSpec{
				ForProvider: &s3v1beta1.BucketVersioningSpecForProvider{
					Region:                  xr.Spec.Region,
					BucketSelector:          &s3v1beta1.BucketVersioningSpecForProviderBucketSelector{MatchControllerRef: ptr.To(true)},
					VersioningConfiguration: &s3v1beta1.BucketVersioningSpecForProviderVersioningConfiguration{Status: ptr.To("Enabled")},
				},
			},
		}
		if err := addDesired(desired, "versioning", versioning); err != nil {
			response.Fatal(rsp, err)
			return rsp, nil
		}
	}

	if err := response.SetDesiredComposedResources(rsp, desired); err != nil {
		response.Fatal(rsp, errors.Wrap(err, "cannot set desired composed resources"))
		return rsp, nil
	}

	// Status from an observed composed resource, keyed by composition resource name.
	observed, err := request.GetObservedComposedResources(req)
	if err != nil {
		response.Fatal(rsp, errors.Wrap(err, "cannot get observed composed resources"))
		return rsp, nil
	}
	if b, ok := observed["bucket"]; ok {
		if arn, err := b.Resource.GetString("status.atProvider.arn"); err == nil {
			dxr, err := request.GetDesiredCompositeResource(req)
			if err != nil {
				response.Fatal(rsp, errors.Wrap(err, "cannot get desired composite resource"))
				return rsp, nil
			}
			if err := dxr.Resource.SetString("status.bucketArn", arn); err != nil {
				response.Fatal(rsp, errors.Wrap(err, "cannot set status.bucketArn"))
				return rsp, nil
			}
			if err := response.SetDesiredCompositeResource(rsp, dxr); err != nil {
				response.Fatal(rsp, errors.Wrap(err, "cannot set desired composite resource"))
				return rsp, nil
			}
		}
	}

	response.ConditionTrue(rsp, "FunctionSuccess", "Success").TargetComposite() // not ...AndClaim: v2 XRs have no claim
	return rsp, nil
}

// addDesired stores a typed model under a composition resource name. The
// generated models are not runtime.Objects, so composed.From and
// resource.AsStruct do not accept them: round-trip through JSON instead.
func addDesired(desired map[resource.Name]*resource.DesiredComposed, name resource.Name, model any) error {
	c := composed.New()
	if err := convertViaJSON(c, model); err != nil {
		return errors.Wrapf(err, "cannot convert %s", name)
	}
	desired[name] = &resource.DesiredComposed{Resource: c}
	return nil
}

func convertViaJSON(to, from any) error {
	bs, err := json.Marshal(from)
	if err != nil {
		return err
	}
	return json.Unmarshal(bs, to)
}
```

### Several status fields

The template writes one status field. For several, get `dxr` once, set every field on it, each
inside its own observed-resource branch, and call `response.SetDesiredCompositeResource` once
before returning. Don't repeat the template's get-set-set block per field:
`request.GetDesiredCompositeResource(req)` builds a new object from the request on every call,
and `SetDesiredCompositeResource` replaces the response's composite whole. Whether an earlier
field survives then depends on the request: `response.To` shares the request's desired state with
the response, so it survives when the request carries one, and is lost when it does not, as in a
unit-test request built with `Observed` only (checked against v0.5.0).

**There is no stale status to clear.** Crossplane starts every pipeline run with an empty desired
state ("The Function pipeline starts with empty desired state", in the composite controller's
`composition_functions.go`; `crossplane render` does the same), so the first step starts the XR's
desired status from nothing on every reconcile; only a later step receives an earlier step's
desired state. Crossplane then applies the XR status with server-side apply, as the pipeline's
fully specified intent, so a field the pipeline stops writing is removed, not left behind
(checked in the Crossplane source, v1.20 to v2.2). Write no code or test that clears status
left by an earlier reconcile.

## Unit-test template: the fast tier (`functions/<n>/fn_test.go`)

`go test ./...` in `functions/<n>/` calls `RunFunction` directly: about a second, no project build. It is
also where absence goes: `assertResources` cannot say a field is absent; a Go unit test on the desired
state can. Asserting the exact set of resource names catches a surplus resource too.

The unit test supplements `up test run`; it never replaces it. It does not run the composition pipeline,
the XRD defaults, or the other functions.

```go
package main

import (
	"context"
	"slices"
	"testing"

	"github.com/crossplane/function-sdk-go/logging"
	fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
	"github.com/crossplane/function-sdk-go/resource"
)

func TestRunFunction(t *testing.T) {
	cases := map[string]struct {
		xr        string
		wantNames []string // the exact set of composition resource names
	}{
		"VersioningOff": {
			xr:        `{"apiVersion":"demo.example.org/v1alpha1","kind":"Bucket","metadata":{"name":"example","namespace":"default"},"spec":{"region":"eu-central-1"}}`,
			wantNames: []string{"bucket"},
		},
		"VersioningOn": {
			xr:        `{"apiVersion":"demo.example.org/v1alpha1","kind":"Bucket","metadata":{"name":"example","namespace":"default"},"spec":{"region":"eu-central-1","versioning":true}}`,
			wantNames: []string{"bucket", "versioning"},
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			req := &fnv1.RunFunctionRequest{
				Observed: &fnv1.State{Composite: &fnv1.Resource{Resource: resource.MustStructJSON(tc.xr)}},
			}
			rsp, err := (&Function{log: logging.NewNopLogger()}).RunFunction(context.Background(), req)
			if err != nil {
				t.Fatal(err)
			}
			for _, r := range rsp.GetResults() { // errors arrive as Fatal results, not as err
				if r.GetSeverity() == fnv1.Severity_SEVERITY_FATAL {
					t.Fatalf("fatal result: %s", r.GetMessage())
				}
			}
			var got []string
			for n := range rsp.GetDesired().GetResources() {
				got = append(got, n)
			}
			slices.Sort(got) // map order is random
			if !slices.Equal(got, tc.wantNames) {
				t.Errorf("desired resources: want %v, got %v", tc.wantNames, got)
			}
			// Absence, which assertResources cannot express: forProvider holds region and nothing else.
			bucket := rsp.GetDesired().GetResources()["bucket"].GetResource().AsMap()
			fp, _ := bucket["spec"].(map[string]any)["forProvider"].(map[string]any)
			if len(fp) != 1 || fp["region"] != "eu-central-1" {
				t.Errorf("bucket forProvider: want only region, got %v", fp)
			}
		})
	}
}
```

A property of *every* composed resource (a label, a policy, a config ref, a region) goes in one loop over
the whole desired state, inside the `t.Run` above, so a resource that misses it cannot hide behind
per-resource expectations. Here every resource carries the XR's region:

```go
for name, r := range rsp.GetDesired().GetResources() {
	sp, _ := r.GetResource().AsMap()["spec"].(map[string]any)
	if fp, _ := sp["forProvider"].(map[string]any); fp["region"] != "eu-central-1" {
		t.Errorf("%s: forProvider.region: want eu-central-1, got %v", name, fp["region"])
	}
}
```

`GetDesired().GetResources()` is a `map[string]*fnv1.Resource`: index it with a `string`, not a
`resource.Name`. A status branch needs observed composed state, which the template does not feed. In a
unit test, key `Observed.Resources` by composition resource name; the SDK uses that map key, not the
annotation inside (in a CompositionTest the renderer builds that key from each mock's
composition-resource-name annotation: `charter/evidence.md`, Coverage):

```go
req := &fnv1.RunFunctionRequest{Observed: &fnv1.State{
	Composite: &fnv1.Resource{Resource: resource.MustStructJSON(tc.xr)},
	Resources: map[string]*fnv1.Resource{
		"bucket": {Resource: resource.MustStructJSON(`{"apiVersion":"s3.aws.m.upbound.io/v1beta1","kind":"Bucket","status":{"atProvider":{"arn":"arn:aws:s3:::example"}}}`)},
	},
}}
// after RunFunction, as in the template:
st, _ := rsp.GetDesired().GetComposite().GetResource().AsMap()["status"].(map[string]any)
if st["bucketArn"] != "arn:aws:s3:::example" {
	t.Errorf("status.bucketArn: got %v", st["bucketArn"])
}
if rsp.GetDesired().GetResources()["bucket"].GetReady() != fnv1.Ready_READY_UNSPECIFIED {
	t.Error("bucket: Ready set, want unset")
}
```

### A path that must return Fatal

The template fails on any Fatal. For an input the function must reject, write a sibling test that
expects one: a composition test can't (author-tests, "A Fatal result"). It asserts the message, that
nothing was composed, and that no success condition was set. "Nothing composed" is measurable because
a request built with `Observed` only carries no desired state for `response.To` to copy.

```go
// fatalMessages returns the message of every Fatal result in rsp.
func fatalMessages(rsp *fnv1.RunFunctionResponse) []string {
	var msgs []string
	for _, r := range rsp.GetResults() {
		if r.GetSeverity() == fnv1.Severity_SEVERITY_FATAL {
			msgs = append(msgs, r.GetMessage())
		}
	}
	return msgs
}

func TestRunFunctionMissingRegion(t *testing.T) {
	req := &fnv1.RunFunctionRequest{Observed: &fnv1.State{Composite: &fnv1.Resource{
		Resource: resource.MustStructJSON(`{"apiVersion":"demo.example.org/v1alpha1","kind":"Bucket","metadata":{"name":"example","namespace":"default"},"spec":{}}`),
	}}}
	rsp, err := (&Function{log: logging.NewNopLogger()}).RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	if got := fatalMessages(rsp); len(got) != 1 || got[0] != "spec.region is required" {
		t.Errorf("fatal results: want [spec.region is required], got %q", got)
	}
	if n := len(rsp.GetDesired().GetResources()); n != 0 {
		t.Errorf("desired resources: want none, got %d", n)
	}
	for _, c := range rsp.GetConditions() {
		if c.GetType() == "FunctionSuccess" {
			t.Error("FunctionSuccess set on a fatal path")
		}
	}
}
```

Checked against function-sdk-go v0.5.0 with a function that returns this Fatal the way the template
does: it passes, and disabling the Fatal branch turns all three checks red.

## Failure modes

| What you do | What happens |
|---|---|
| `go build ./...` in `functions/<n>/` | writes `./<n>`, about 55 MB, and `git add functions/<n>` commits it |
| Leave the scaffold `fn_test.go` as it is | `go test` prints `ok`; zero cases ran |
| `composed.From(model)` or `resource.AsStruct(x)` with a model or an `any` | compile or vet error: `does not implement runtime.Object (missing method DeepCopyObject)` |
| Import the non-`.m.` model in a v2 project | compiles; the rendered resource carries the cluster-scoped `apiVersion` |
| Guess a constant such as `BucketAPIVersions3AwsMUpboundIoV1Beta1` | the spelling varies per kind (`VPCApiVersion…`, `SubnetAPIVersion…`); read the `const (` block of that kind's file |
| Pass a model constant as a `string` | `cannot use … (constant of string type …) as string value`: the constants are typed, use `string(c)` |
| Delete the models `replace` as unused | the first model import fails: `unrecognized import path "dev.upbound.io/models"` |
