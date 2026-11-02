# Go: tests

- [How `up` runs a Go test](#how-up-runs-a-go-test)
- [Models in a test](#models-in-a-test)
- [Composition test template (`tests/test-<n>/main.go`)](#composition-test-template-teststest-nmaingo)
- [E2E tests](#e2e-tests)
- [Go-specific failure modes (reproduced)](#go-specific-failure-modes-reproduced)

Composition tests for a project whose functions are written in Go. What the suite must contain is in
[`charter/evidence.md` § Coverage](../../charter/evidence.md#coverage-what-the-suite-must-contain) and
applies unchanged.

Everything here was run against `up` v0.55.0: the template below passes, a flipped expectation and a function
mutant both turn it red, and the failure modes in the last section are reproduced, not guessed.

## How `up` runs a Go test

| | |
|---|---|
| Scaffold | `up test generate <n> --language go` → `tests/test-<n>/{go.mod,main.go}`, no `go.sum`: run `go mod tidy` before your own `go vet`, `go build` or `go run .` (`up test run` tidies first). Pass the bare name: `up` adds the prefix (`test-x` gives `tests/test-test-x`; with `--e2e`, `e2etest-`) |
| Detected by | a `go.mod` in the test directory |
| Generation | `go mod tidy`, then `go run .`, both **with the test directory as CWD**, in your working tree, on your machine (no container). A file the program opens itself resolves from `tests/test-<n>/`; the paths it *emits* (`compositionPath`, `xrdPath`) are resolved by `up` from the project root |
| Contract | the program prints `{items: [CompositionTest, …]}` as YAML on stdout. A non-zero exit fails the whole run at `✗ Parsing tests`, before any render. |

Consequences:

- **The program generates tests; it is not one.** Assertions go in `assertResources`, where `up` evaluates them
  against a render.
  For checks that are not a render, see `author-tests` "Checking what is not a render".
- **Commit `go.mod` and `go.sum` after running `go mod tidy` yourself.** `up test run` tidies in place, so an
  untidy module leaves the tree dirty after every test run.
- Composition tests read nothing from the environment (what the program sees: [`../go.md`](../go.md#where-go-runs)).
- **Output must be deterministic.** Never range over a Go map to build a list you assert: map iteration order
  is random, and lists are compared exactly, so the test flakes. No `time.Now()`, no randomness.

## Models in a test

**Use typed models for composed-resource expectations**: a misspelt or mis-shaped `forProvider` field does not
compile, the main thing Go buys you over YAML. Every model field is a pointer with `omitempty`, so only
what you set is serialised and the assertion stays partial. **Use plain maps for the XR fixture,
`observedResources` and expectations on the composite:** those are `map[string]interface{}` in the test model
anyway, and a map lets you write exactly the partial shape you mean (e.g. only `status`, or only
`spec.crossplane.resourceRefs`).

A real case from writing the template below: the function and a map-based expectation both wrote
`versioningConfiguration` as a list, the shape of the old cluster-scoped API. Function and test agreed, so the
test passed — but in the namespaced `v1beta1` API it is an object, and only schema validation caught it. With the
typed `BucketVersioning` model the list does not compile.

## Composition test template (`tests/test-<n>/main.go`)

Three tests for the function template in [`functions.md`](functions.md): one per input branch (with an
absence guard on the composite) and one observed-state test that drives a status field. Adapt the helpers; keep
the shape. The shipped-example test (charter `evidence.md`, Coverage) sets
`spec.XrPath = ptr.To("examples/<…>.yaml")` and leaves `Xr` nil: with both set, `up test run` fails
validation. The path resolves from the project root, like `compositionPath`.

```go
// Package main generates the composition tests for Bucket.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"k8s.io/utils/ptr"
	"sigs.k8s.io/yaml"

	metav1 "dev.upbound.io/models/io/k8s/meta/v1"
	metav1alpha1 "dev.upbound.io/models/io/upbound/dev/meta/v1alpha1"
	s3v1beta1 "dev.upbound.io/models/io/upbound/m/aws/s3/v1beta1"
)

const (
	compositionPath = "apis/buckets/composition.yaml"
	xrdPath         = "apis/buckets/definition.yaml"
)

func main() {
	tests := []metav1alpha1.CompositionTest{
		// Input branch: versioning off. resourceRefs on the composite is a list, and lists match exactly, so a
		// surplus BucketVersioning fails this test. Names copied from render.log (renders are deterministic).
		compositionTest("versioning-disabled", inlineXR(map[string]any{"region": "eu-central-1"}), nil,
			bucket("eu-central-1"),
			composite(map[string]any{"spec": map[string]any{"crossplane": map[string]any{"resourceRefs": []any{
				map[string]any{"apiVersion": "s3.aws.m.upbound.io/v1beta1", "kind": "Bucket", "name": "example-963082b09556"},
			}}}}),
		),
		compositionTest("versioning-enabled", inlineXR(map[string]any{"region": "eu-central-1", "versioning": true}), nil,
			bucket("eu-central-1"),
			versioning("eu-central-1"),
		),
		// Fails if the mock is ignored: bucketArn can only come from it. What a mock needs, and what its name
		// does (this one equals the generated name): charter/evidence.md, Coverage.
		compositionTest("status-from-observed-bucket", inlineXR(map[string]any{"region": "eu-central-1"}),
			[]any{map[string]any{
				"apiVersion": "s3.aws.m.upbound.io/v1beta1",
				"kind":       "Bucket",
				"metadata": map[string]any{
					"name": "example-963082b09556", "namespace": "default",
					"annotations": map[string]any{"crossplane.io/composition-resource-name": "bucket"},
				},
				"spec":   map[string]any{"forProvider": map[string]any{"region": "eu-central-1"}},
				"status": map[string]any{"atProvider": map[string]any{"arn": "arn:aws:s3:::example"}},
			}},
			bucket("eu-central-1"), // a status-only test would stay green if this branch stopped composing the bucket
			composite(map[string]any{"status": map[string]any{"bucketArn": "arn:aws:s3:::example"}}),
		),
	}
	if len(tests) == 0 { // an empty items list is not an error to up: the run just has fewer tests
		fmt.Fprintln(os.Stderr, "no tests generated")
		os.Exit(1)
	}
	out, err := yaml.Marshal(map[string]any{"items": tests})
	if err != nil {
		fmt.Fprintf(os.Stderr, "encoding YAML: %v\n", err)
		os.Exit(1)
	}
	fmt.Print(string(out))
}

func bucket(region string) s3v1beta1.Bucket {
	return s3v1beta1.Bucket{
		APIVersion: ptr.To(s3v1beta1.BucketAPIVersions3AwsMUpboundIoV1Beta1),
		Kind:       ptr.To(s3v1beta1.BucketKindBucket),
		Metadata:   crn("bucket"),
		Spec: &s3v1beta1.BucketSpec{
			ForProvider: &s3v1beta1.BucketSpecForProvider{Region: ptr.To(region)},
		},
	}
}

// versioning uses the typed model: had the expectation been written as a list (the old, cluster-scoped shape),
// it would not compile - in the namespaced v1beta1 API versioningConfiguration is an object.
func versioning(region string) s3v1beta1.BucketVersioning {
	return s3v1beta1.BucketVersioning{
		APIVersion: ptr.To(s3v1beta1.BucketVersioningAPIVersions3AwsMUpboundIoV1Beta1),
		Kind:       ptr.To(s3v1beta1.BucketVersioningKindBucketVersioning),
		Metadata:   crn("versioning"),
		Spec: &s3v1beta1.BucketVersioningSpec{
			ForProvider: &s3v1beta1.BucketVersioningSpecForProvider{
				Region:                  ptr.To(region),
				BucketSelector:          &s3v1beta1.BucketVersioningSpecForProviderBucketSelector{MatchControllerRef: ptr.To(true)},
				VersioningConfiguration: &s3v1beta1.BucketVersioningSpecForProviderVersioningConfiguration{Status: ptr.To("Enabled")},
			},
		},
	}
}

func crn(name string) *metav1.ObjectMeta {
	return &metav1.ObjectMeta{Annotations: &map[string]string{"crossplane.io/composition-resource-name": name}}
}

func inlineXR(spec map[string]any) map[string]any {
	return map[string]any{
		"apiVersion": "demo.example.org/v1alpha1",
		"kind":       "Bucket",
		"metadata":   map[string]any{"name": "example", "namespace": "default"},
		"spec":       spec,
	}
}

// composite is an expectation on the XR itself. Partial like every assertion, except that lists match exactly.
func composite(fields map[string]any) map[string]any {
	c := map[string]any{"apiVersion": "demo.example.org/v1alpha1", "kind": "Bucket", "metadata": map[string]any{"name": "example"}}
	for k, v := range fields {
		c[k] = v
	}
	return c
}

func compositionTest(name string, xr map[string]any, observed []any, asserts ...any) metav1alpha1.CompositionTest {
	ar := resourcesToItems[metav1alpha1.CompositionTestSpecAssertResourcesItem](asserts...)
	spec := &metav1alpha1.CompositionTestSpec{
		AssertResources: &ar,
		CompositionPath: ptr.To(compositionPath),
		XrdPath:         ptr.To(xrdPath),
		Xr:              ptr.To(metav1alpha1.CompositionTestSpecXr(xr)),
		TimeoutSeconds:  ptr.To(120),
		Validate:        ptr.To(false),
	}
	if len(observed) > 0 {
		obs := resourcesToItems[metav1alpha1.CompositionTestSpecObservedResourcesItem](observed...)
		spec.ObservedResources = &obs
	}
	return metav1alpha1.CompositionTest{
		APIVersion: ptr.To(metav1alpha1.CompositionTestAPIVersionmetaDevUpboundIoV1Alpha1),
		Kind:       ptr.To(metav1alpha1.CompositionTestKindCompositionTest),
		Metadata:   &metav1.ObjectMeta{Name: ptr.To(name)},
		Spec:       spec,
	}
}

func resourcesToItems[T any](resources ...any) []T {
	items := make([]T, 0, len(resources))
	for _, r := range resources {
		var item T
		bs, err := json.Marshal(r)
		if err == nil {
			err = json.Unmarshal(bs, &item)
		}
		if err != nil {
			panic(fmt.Sprintf("converting item: %v", err))
		}
		items = append(items, item)
	}
	return items
}
```

**Add a case to this program before scaffolding another** (author-tests, Phase 2): each test
directory is its own `package main` module, so no other can import its helpers. As it grows,
split it into files of the one package (`main.go`, `xr.go`, `expect_<concern>.go`).

Run it and read the render before trusting an expectation you typed
([`charter/evidence.md`](../../charter/evidence.md) says how, and why the generated `resourceRefs` names
such as `example-963082b09556` are safe to copy):

```bash
gofmt -l tests/ && (cd tests/test-<n> && go vet .)
up test run tests/test-<n> --function-logs     # prints the directory holding each test's render.log;
                                               # --output-dir without --function-logs writes nothing
```

## E2E tests

`up test generate <n> --e2e --language go` scaffolds the same program shape around an `E2ETest`, in
`tests/e2etest-<n>/`. **Read author-tests' `e2e.md` reference before writing or changing one:** it has the Go
E2ETest template, the field defaults (the Go scaffold writes `timeoutSeconds: 300` and no `crossplane` block),
`defaultConditions` as condition types rather than expressions, and credentials per target.
`e2e-test-configuration` runs it.

**A missing input exits non-zero, naming the variable**, so an E2E run stops at parse time instead of after a
control plane and real resources exist. That is safe because the default composition gate is
`up test run "tests/test-*"`, which never runs this program (charter §7; write both commands in the project
README; a project gate of `tests/*` sets the variable too). Do not swap the exit for a placeholder value: the
run would then pass parsing without the credential and fail only at the provider, after a control plane exists.

## Go-specific failure modes (reproduced)

| What you do | What `up test run` does |
|---|---|
| Wrong expected value | that test FAILs (good) |
| An XR that makes the function return a Fatal result | that test FAILs at render, `cannot render composite resource: … returned a fatal result: <msg>`, before any assertion; no field expects an error. Test the fatal path in a unit test ([`functions.md`](functions.md#a-path-that-must-return-fatal)) |
| Function mutant (`if versioning` → `if true`) | only a test with a `resourceRefs` guard FAILs; without it the suite stays green |
| Compile error, panic or non-zero exit in `main.go` | the **whole run** fails at `✗ Parsing tests` (`failed to generate test files: … failed to execute 'go run .'`), no test executes. It reads as a broken test, never as RED |
| E2E program exits on a missing variable under `up test run "tests/*"` | the composition gate fails at `✗ Parsing tests` (`failed to execute 'go run .': <your message>`), though no composition test is wrong |
| `tests/e2etest-<n>` run on its own without `--e2e` | `unable to validate composition tests: no valid CompositionTests found`: the dir produced no `CompositionTest`. Add `--e2e` |
| `items` empty | **nothing fails, and nothing ran from that dir** (charter §8). Exit non-zero on an empty list, as the template does |
