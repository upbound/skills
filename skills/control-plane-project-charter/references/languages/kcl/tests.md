# KCL: tests

Composition and E2E test templates in KCL, and ways to keep several tests in one directory. What a
suite must contain is in [`charter/evidence.md`](../../charter/evidence.md#coverage-what-the-suite-must-contain);
the KCL index is [`../kcl.md`](../kcl.md).

A KCL test module ends with `items = [...]`: that list is what `up` reads. Defining `_items` and
never assigning `items` produces no tests. Paths in a test (`compositionPath`, `xrdPath`,
`xrPath`) are resolved from the project root, as in every language.

## Composition test

```kcl
"""
<Feature> composition test: <the behaviour each test proves>.
"""

import models.io.upbound.awsm.ec2.v1beta1 as ec2v1beta1
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1

_items = [
    metav1alpha1.CompositionTest{
        metadata.name: "test-<resource>-<feature>"
        spec = {
            compositionPath: "apis/<resource>/composition.yaml"
            xrdPath: "apis/<resource>/definition.yaml"
            timeoutSeconds: 60
            validate: False
            xr: {                      # inline XR; xr and xrPath are mutually exclusive
                apiVersion: "aws.platform.upbound.io/v1alpha1"
                kind: "<Kind>"
                metadata: { name: "test-<name>", namespace: "default" }
                spec: { region: "us-west-2", tags: { Environment: "test" } }
            }
            assertResources: [
                ec2v1beta1.VPC{
                    # No metadata.name while VPC appears once in the render; with several,
                    # copy each name from render.log (charter/evidence.md).
                    spec.forProvider: {
                        region: "us-west-2"
                        tags: { Environment: "test" }
                    }
                }
            ]
        }
    }
]
items = _items
```

Expectations carry only what the function sets: no `providerConfigRef` unless the function
writes it ([charter §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)).
A typed expectation such as `ec2v1beta1.VPC{}` also carries the model's default
`managementPolicies: ["*"]` (measured). That matches a KCL function's render, which
materializes the same default ([`charter/v2-resources.md`](../../charter/v2-resources.md)); to
test a function in another language from KCL, write the expectation as a plain dict.

## E2E test
```kcl
"""
E2E Test: <Feature Name>

Validates <feature> with real AWS resources: create, Ready, delete.
"""

import models.io.upbound.awsm.v1beta1 as awsmv1beta1
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1

_items = [
    metav1alpha1.E2ETest{
        metadata.name: "e2etest-<resource>-<feature>"
        spec = {
            crossplane = { autoUpgrade.channel = "Stable" }  # or a deliberately pinned current version
            defaultConditions: ["Ready"]  # condition types; add "Synced" only to gate on sync
            timeoutSeconds: 1800          # size to the real resources
            cleanupTimeoutSeconds: 600
            skipDelete: False

            manifests: [
                {
                    apiVersion: "aws.platform.upbound.io/v1alpha1"
                    kind: "<Kind>"
                    metadata: { name: "e2e-test-<name>", namespace: "default" }
                    spec: { region: "us-west-2", tags: { Environment: "e2e-test" } }
                }
            ]

            extraResources: [
                # Cluster-scoped, so no metadata.namespace: the default every composed MR falls back to.
                awsmv1beta1.ClusterProviderConfig{
                    metadata.name: "default"
                    spec.credentials: {
                        source: "Upbound"
                        upbound.webIdentity.roleARN: "arn:aws:iam::123456789012:role/<role>"
                    }
                }
            ]
        }
    }
]
items = _items
```

Which `credentials` block a target needs (web identity on a Space, a `UP_*` Secret on a local
control plane) is in author-tests' `e2e.md` reference. On another cloud only these change:

| | Azure | GCP |
|---|---|---|
| Import | `models.io.upbound.azurem.v1beta1 as azuremv1beta1` | `models.io.upbound.gcpm.v1beta1 as gcpmv1beta1` |
| `ClusterProviderConfig` web identity, beside `source: "Upbound"` | `spec.clientID`, `spec.tenantID`, `spec.subscriptionID`: not under `spec.credentials` (author-tests' `e2e.md`) | `upbound.federation.{providerID, serviceAccount}`, plus `spec.projectID` |
| Provider field names your XR usually mirrors | `location`, `tags` | `region`, `project`, `labels` (lowercase keys) |

## Several tests in one file

Share the common spec with `**` and generate variants from data, so every test has the same
shape:

```kcl
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1

_baseSpec = {
    compositionPath: "apis/<resource>/composition.yaml"
    xrdPath: "apis/<resource>/definition.yaml"
    timeoutSeconds: 60
    validate: False
}

_variants = [
    { name: "versioning-on", spec: { versioning: True } }
    { name: "versioning-off", spec: { versioning: False } }
]

_buildTest = lambda v {
    metav1alpha1.CompositionTest {
        metadata.name: "test-<resource>-${v.name}"
        spec: {
            **_baseSpec
            xr: {
                apiVersion: "aws.platform.upbound.io/v1alpha1"
                kind: "<Kind>"
                metadata: { name: "test-${v.name}", namespace: "default" }
                spec: { region: "us-west-2", **v.spec }
            }
            assertResources: []        # what this variant expects
        }
    }
}

items = [_buildTest(v) for v in _variants]
```

## Observed state across files

A function that waits for one resource before composing the next needs one test per step, each
feeding the previous resource's status in through `observedResources`. Split the reusable parts
into files of the same test directory:

```text
tests/test-<resource>-sequence/
├── main.k         # the tests
├── resources.k    # resource1, resource2: expectations, each with its crossplane.io/composition-resource-name annotation
├── conditions.k   # shared condition sets
└── kcl.mod
```

```kcl
# conditions.k: a fixed timestamp keeps the generated tests identical between runs
readyConditions = [
    { type: "Ready", status: "True", reason: "Available", lastTransitionTime: "2026-01-01T00:00:00Z" }
    { type: "Synced", status: "True", reason: "ReconcileSuccess", lastTransitionTime: "2026-01-01T00:00:00Z" }
]
```

```kcl
# main.k
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1
import resources
import conditions

_baseSpec = {
    compositionPath: "apis/<resource>/composition.yaml"
    xrdPath: "apis/<resource>/definition.yaml"
    timeoutSeconds: 60
    validate: False            # up test run never reads it (author-tests' test-model.md)
}

_xr = {
    apiVersion: "aws.platform.upbound.io/v1alpha1"
    kind: "<Kind>"
    metadata: { name: "test-<resource>", namespace: "default" }
    spec: { region: "us-west-2" }
}

# A mock is observed only with metadata.name and the XR's namespace; without them it is silently
# ignored (charter/evidence.md). Any valid name works, and the render gives it to the composed
# resource, so this case's assertions name it too.
_resource1Name = "test-<resource>-resource1"

_test1 = metav1alpha1.CompositionTest {
    metadata.name: "sequence-0-initial"
    spec: { **_baseSpec, xr: _xr, assertResources: [resources.resource1] }
}

_test2 = metav1alpha1.CompositionTest {
    metadata.name: "sequence-1-resource1-ready"
    spec: {
        **_baseSpec
        xr: _xr
        observedResources: [
            # `metadata:` merges and keeps the annotation from resources.k; `metadata =` drops it
            resources.resource1 | {
                metadata: { name: _resource1Name, namespace: _xr.metadata.namespace }
                status: { atProvider: { id: "id1" }, conditions: conditions.readyConditions }
            }
        ]
        assertResources: [
            resources.resource1 | { metadata: { name: _resource1Name } }
            resources.resource2
        ]
    }
}

items = [_test1, _test2]
```

Omit `conditions` for the "observed but not ready" step: the two cases separate a readiness
check from an existence check.
