# Writing an E2ETest

Read before writing or changing any `E2ETest`, in any language. Running one (target, monitoring, report) is
`e2e-test-configuration`'s job. Facts come from the up v0.55.0 source and runs; they may change between
versions.

## What happens on the control plane

On any target, in this order:

1. Every matched test program runs (`Parsing tests`) before any control plane exists.
2. The control plane is created, then `initResources` are applied, then the package is installed and waited for.
3. `extraResources` are server-side applied: no wait, no condition check.
4. The manifests are applied and `defaultConditions` asserted within `timeoutSeconds`.
5. Teardown follows every test that got past setup, pass or fail: the test's resources, then the control
   plane. `skipDelete: true` or `--skip-control-plane-cleanup` leaves the control plane up, and a setup failure
   or a panic skips teardown silently (e2e-test-configuration's `local.md`, Leaks).

`--function-logs` is rejected with `--e2e`: an e2e run writes no `render.log`, so its output and exit code are
the only record.

## Fields

An `E2ETest` has **no** `compositionPath`, `xrdPath` or `xr`. It applies real manifests to a fresh control
plane and waits for conditions.

| Field | Meaning | Unset |
|---|---|---|
| `metadata.name` | test name; the control plane is `<project>-uptest-<name>` by default | every scaffold except YAML (`basic-e2e-test`) leaves `""`: set it |
| `spec.crossplane` | `autoUpgrade.channel: Stable\|Rapid` (no pinned version), or a deliberately pinned *current* `version`. A local control plane ignores the channel | latest matching version; the Go scaffold omits the block |
| `spec.defaultConditions` | condition **types** every manifest must reach (below) | scaffolds set `["Ready"]` |
| `spec.manifests` | resources under test, ≥1, usually the XR. The only objects asserted | — |
| `spec.extraResources` | Namespace, credential Secret, ProviderConfig: applied after the package is ready, **never asserted** | — |
| `spec.initResources` | applied before the package is installed (ImageConfig, DeploymentRuntimeConfig) | — |
| `spec.timeoutSeconds` | sized to what you provision: a couple of resources ~900s, an EKS cluster with add-ons 3600–5400s | **No default: set it explicitly.** If it is omitted, the run builds, creates the control plane, installs the package and then panics (`nil pointer dereference`, exit 2) without teardown, so the control plane leaks (observed with up v0.55.0; e2e-test-configuration's `local.md`, Leaks). Every scaffold sets it: Go to 300, the others to 4500 |
| `spec.cleanupTimeoutSeconds` | proportional to teardown time | 600 |
| `spec.setupTimeoutSeconds` | control plane creation, package install, resources | 600 |
| `spec.skipDelete` | **always `false`** | `false` |

## `defaultConditions` lists condition types, not expressions

Each entry becomes this assertion on every object in `spec.manifests` (not composed resources, not
`extraResources`):

```text
((conditions[?type == '<entry>'])[0]).status == "True"
```

It checks one condition type for `status: "True"` and nothing else: no reason, message or field value. The
generated model calls each entry "a string expression"; that is wrong. Observed with up v0.55.0:

| Entry | Result |
|---|---|
| `Ready` (add `Synced` only to gate on sync) | the intended check |
| a status path or any other string without a `'` (`status.vpcId`, `status.vpcId != null`) | parses, builds and creates the control plane, then fails only after the full `timeoutSeconds`, even on a Ready XR: `field not found in the input object` |
| a string containing `'` (`status.vpcId == 'vpc-123'`) | `SyntaxError: Expected TOKRbracket, …` at the assert step, still after the build and setup |

The last two are broken tests, not RED. Nothing checks an entry when the test is parsed, so check every entry
before a run: each bad one costs a full build, a control plane and `timeoutSeconds`.

## The ProviderConfig the test creates

`up test generate --e2e` emits `extraResources: []` in every language: the test creates no ProviderConfig
until you add one. Add the one the composed resources reference:

| Kind | Scope | `metadata.namespace` | When |
|---|---|---|---|
| `ClusterProviderConfig` named `default` | cluster | none — omit it | **the default.** A managed resource with no `providerConfigRef` is defaulted to `{kind: ClusterProviderConfig, name: default}` |
| `ProviderConfig` | namespaced | the XR's (`default`) | only when the composition sets `providerConfigRef.kind: ProviderConfig`; same name it references |

Its `apiVersion` is the provider family's group (`aws.m.upbound.io/v1beta1`), not a service group. A mismatch
between what the test creates and what the resources reference fails only on the control plane; the symptoms are
in `control-plane-project-charter/references/charter/v2-resources.md`. The language files show the syntax only.

## Credentials depend on the target

| Target | ProviderConfig `credentials` |
|---|---|
| Spaces control plane | `source: Upbound` (web identity). The only `up` command that generates it, `up controlplane oidc-auth aws`, requires a Spaces control plane context. Each test gets its own control plane, so the trust policy needs a wildcard subject (inference, untested) |
| Local control plane (`--local`, kind) | static Secret: `source: Secret` plus `secretRef: {namespace, name, key}`. `secret:` is rejected as `field not declared in schema` |

Other providers use the same structure with their own credential format as the Secret's value. For AWS the
value is a credentials file's text, never its path, exported whole under a `UP_` name such as
`UP_AWS_CREDENTIALS` (KCL and Python programs see only `UP_*` variables; charter §7):

```ini
[default]
aws_access_key_id = <placeholder>
aws_secret_access_key = <placeholder>
aws_session_token = <placeholder>
```

A typo such as `session_token` passes every check and fails only at the provider, with `InvalidClientTokenId`.
Web-identity fields on Spaces, each with `credentials.source: Upbound`:

- AWS: `credentials.upbound.webIdentity.roleARN`.
- Azure: `spec.clientID`, `spec.tenantID` and `spec.subscriptionID`, beside `credentials`, not under it. The
  Azure `ClusterProviderConfig` has no `upbound` block (provider-family-azure v2.7.2 CRD), so the API server
  drops an `upbound.webIdentity.clientID` and the run fails at authentication.
- GCP: `credentials.upbound.federation.{providerID, serviceAccount}` plus `spec.projectID`.

**Never commit a real value**, and never inline long-lived keys in a test: use web identity, or a Secret filled
from a `UP_*` variable.

Build `UP_AWS_CREDENTIALS` in memory from the session's `AWS_*` variables, in the same command as `up test run`
(an export from an earlier command is gone by then): one `printf`, no file, no umask change (drop the token line
for long-lived keys). In e2e-test-configuration's run block, put the `export` first:

```bash
# For up test run only. To read or diff a program's output, from the test directory, with a dummy value:
# Go: UP_AWS_CREDENTIALS=x go run .   Python SDK: UP_AWS_CREDENTIALS=x ../../.venv/bin/python -m test
export UP_AWS_CREDENTIALS="$(printf '[default]\naws_access_key_id = %s\naws_secret_access_key = %s\naws_session_token = %s\n' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "$AWS_SESSION_TOKEN")"
up test run "tests/e2etest-<n>" --e2e <target flags>
```

A `--local` run started under `umask 077`, a common way to protect a credentials file, never gets its package
ready (e2e-test-configuration's `local.md` reference). If you must write a file, `chmod 600` that file instead.

**The program's output carries the credential.** The Secret in `extraResources` holds the variable's value, so
whatever prints the generated `E2ETest` prints the credential. Check the program with a dummy value (Go
`UP_AWS_CREDENTIALS=x go run .`; Python SDK `UP_AWS_CREDENTIALS=x ../../.venv/bin/python -m test`, from the
test directory), or select `.items[].spec.manifests`; never print its output, or any Secret,
with real values, and never write it to a file. To compare output across commits, diff two dummy runs: the
Secret's value is the only difference real values make. The template below says so in its header comment and
its fail message: keep both in every copy, since later runs read the program, not this page.

## Go template (`tests/e2etest-<n>/main.go`)

Compiles and parses (`✓ Parsing tests`); its spec mirrors a Go E2ETest that passed on a local control plane
with up v0.55.0, and its `ClusterProviderConfig` entry is checked by compiling and running the program only.
Rename the placeholders; keep the shape.

```go
// Package main generates the E2ETest for <Kind>: apply the example XR, wait for Ready, delete everything.
// Its output carries the credential Secret: by hand (incl. diffs) run it only with UP_AWS_CREDENTIALS=x,
// never print or save it with real values.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"k8s.io/utils/ptr"
	"sigs.k8s.io/yaml"

	metav1 "dev.upbound.io/models/io/k8s/meta/v1"
	metav1alpha1 "dev.upbound.io/models/io/upbound/dev/meta/v1alpha1"
)

const (
	exampleXR = "../../examples/<kind>/<xr-name>.yaml" // CWD is tests/e2etest-<n>/; find the file
	namespace = "default"                              // the example XR's metadata.namespace
	credsVar  = "UP_AWS_CREDENTIALS"                   // INI file contents; UP_ by convention
)

func main() {
	// Fail before a control plane exists. Safe while the composition gate is "tests/test-*"; a
	// gate that globs "tests/*" runs this program too and needs this variable set.
	creds := os.Getenv(credsVar)
	if creds == "" {
		fail("%s is not set: set it for up test run --e2e; to read this output by hand, set it to x", credsVar)
	}
	raw, err := os.ReadFile(exampleXR)
	if err != nil {
		fail("reading %s: %v", exampleXR, err)
	}
	var xr map[string]any
	if err := yaml.Unmarshal(raw, &xr); err != nil || len(xr) == 0 {
		fail("parsing %s: %v", exampleXR, err)
	}
	manifests := resourcesToItems[metav1alpha1.E2ETestSpecManifestsItem](xr)
	extra := resourcesToItems[metav1alpha1.E2ETestSpecExtraResourcesItem](
		map[string]any{"apiVersion": "v1", "kind": "Namespace", "metadata": map[string]any{"name": namespace}},
		map[string]any{"apiVersion": "v1", "kind": "Secret",
			"metadata":   map[string]any{"name": "<provider>-creds", "namespace": namespace},
			"stringData": map[string]any{"credentials": creds}},
		// What resources with no providerConfigRef default to. If the composition references a
		// namespaced ProviderConfig, create that kind and name in the XR's namespace instead.
		map[string]any{"apiVersion": "aws.m.upbound.io/v1beta1", "kind": "ClusterProviderConfig",
			"metadata": map[string]any{"name": "default"},
			"spec": map[string]any{"credentials": map[string]any{"source": "Secret",
				"secretRef": map[string]any{"namespace": namespace, "name": "<provider>-creds", "key": "credentials"}}}},
	)
	test := metav1alpha1.E2ETest{
		APIVersion: ptr.To(metav1alpha1.E2ETestAPIVersionmetaDevUpboundIoV1Alpha1),
		Kind:       ptr.To(metav1alpha1.E2ETestKindE2ETest),
		Metadata:   &metav1.ObjectMeta{Name: ptr.To("<n>")},
		Spec: &metav1alpha1.E2ETestSpec{
			Crossplane: &metav1alpha1.E2ETestSpecCrossplane{AutoUpgrade: &metav1alpha1.E2ETestSpecCrossplaneAutoUpgrade{
				Channel: ptr.To(metav1alpha1.E2ETestSpecCrossplaneAutoUpgradeChannelStable)}},
			DefaultConditions:     &[]string{"Ready"}, // condition types, never expressions
			Manifests:             &manifests,
			ExtraResources:        &extra,
			TimeoutSeconds:        ptr.To(1200), // sized to what this provisions
			CleanupTimeoutSeconds: ptr.To(600),
			SkipDelete:            ptr.To(false),
		},
	}
	out, err := yaml.Marshal(map[string]any{"items": []any{test}})
	if err != nil {
		fail("encoding YAML: %v", err)
	}
	fmt.Print(string(out))
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
```

`resourcesToItems` is the helper from the composition-test template in
`control-plane-project-charter/references/languages/go/tests.md`. The E2E run is
`up test run "tests/e2etest-<n>" --e2e …`; the composition gate stays `"tests/test-*"`, and both go in the
project README. If the project's own gate runs `up test run tests/*`, that run needs the e2e inputs set
too; say so in the README and the report (`control-plane-project-charter/references/charter/container.md`).

## E2E RED

An e2e RED is optional (charter §3): it costs a real control-plane run, so take it when it is cheap, else
report the E2ETest as unproven. Composition and unit tests still require RED.

A valid e2e RED is an **implementation mutation** the control plane rejects or never readies: drop a composed
resource the others depend on, or break a selector. Run it with a short `timeoutSeconds` (300) so the RED costs
minutes. Check the failure is the Ready assertion: the error line names `((conditions[?type == 'Ready'])[0])`.
The diff's `status: {}` is not the real status. Make sure the failure isn't a credential error, then revert with
git, after keeping any uncommitted work in the mutated file
(`control-plane-project-charter/references/charter/tdd.md`), and restore the timeout. Editing
`defaultConditions` or an expected value is not RED, and an unparsable condition is a broken test.

## What an E2ETest cannot assert

An `E2ETest` checks one thing: each condition type in `defaultConditions` (normally `Ready`) is `True` on
each object in `spec.manifests`. It cannot assert a status field such as `status.vpcId`, a condition's reason
or message, or anything on a composed resource; `assertResources` exists only on `CompositionTest`, which is
render-only. A second `E2ETest` that differs from another only in its name asserts the same `Ready` and adds a
full control-plane run to every gate. To check a status field or condition, use:

1. a `CompositionTest` whose `observedResources` mock the provider's status, asserting the composite's `status`,
   which proves status derivation;
2. a function unit test;
3. a read-back during the run, if you took one, quoted as "read-back, not asserted" (e2e-test-configuration's
   `local.md`, "Reading a status during the run").

**A read-back is report evidence, not an assertion:** no `E2ETest` field can gate on it, and re-running a green
e2e only to read it costs a full control-plane run. When a provider read works: `local.md`, "A provider read".

uptest's `uptest.upbound.io/pre-assert-hook` and `post-assert-hook` annotations exist in the uptest `up` bundles,
but they are not a supported way to assert status (upbound/up#1720): `up` writes each manifest to a temporary
directory, the hook path resolves against it, and ordinary paths fail.
