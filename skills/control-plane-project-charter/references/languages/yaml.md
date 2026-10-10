# YAML

Raw-YAML tests, with real examples. YAML is a test language only: there are no YAML composition
functions. It shows the test object model with no language in the way, so the other language
references point here for it. When to write tests in YAML rather than the composition language:
[charter §10](../../SKILL.md#10-language-dispatch).

| | |
|---|---|
| Scaffold a test | `up test generate <n> --language yaml` (add `--e2e`) |
| Run one | `up test run "tests/<n>"` |

- **No imports.** The `.m.` lives in the `apiVersion` string (`s3.aws.m.upbound.io/v1beta1`,
  `kubernetes.m.crossplane.io/v1alpha1`, `helm.m.crossplane.io/v1beta1`).
- **Several tests per file**, separated by `---`.
- **Comment what each test proves** and what it deliberately does not cover; real configurations
  do, and it makes the suite readable without the function open.

## Composition test (real example)

Two `CompositionTest` documents in one `test.yaml`, each rendering the composition against an
inline XR.

```yaml
# tests/test-controlplane/test.yaml
apiVersion: meta.dev.upbound.io/v1alpha1
kind: CompositionTest
metadata:
  name: basic
spec:
  compositionPath: apis/ctp/composition.yaml
  xrdPath: apis/ctp/definition.yaml
  validate: false
  timeoutSeconds: 60
  xr:
    apiVersion: aws.platform.upbound.io/v1alpha1
    kind: ControlPlane
    metadata:
      name: test-cp
    spec:
      parameters:
        id: test-cp
        region: us-east-1
        version: "1.34"
        nodes:
          count: 2
          instanceType: t3.small
  assertResources:
  - apiVersion: aws.platform.upbound.io/v1alpha1
    kind: Network
    metadata:
      name: test-cp
  - apiVersion: aws.platform.upbound.io/v1alpha1
    kind: EKS
    metadata:
      name: test-cp
  # Assert the fields that matter, not just existence: here the chart version.
  - apiVersion: helm.m.crossplane.io/v1beta1
    kind: Release
    metadata:
      name: test-cp-uxp
    spec:
      forProvider:
        chart:
          version: "2.2.1-up.1"
---
apiVersion: meta.dev.upbound.io/v1alpha1
kind: CompositionTest
metadata:
  name: backup-enabled          # feature-enabled variant, same directory
spec:
  compositionPath: apis/ctp/composition.yaml
  xrdPath: apis/ctp/definition.yaml
  validate: false
  timeoutSeconds: 60
  xr:
    apiVersion: aws.platform.upbound.io/v1alpha1
    kind: ControlPlane
    metadata:
      name: test-cp
    spec:
      parameters:
        id: test-cp
        region: us-east-1
        version: "1.34"
        nodes: { count: 2, instanceType: t3.small }
        backup:
          enabled: "yes"
          location: arn:aws:s3:::my-backup-bucket
  assertResources:
  # Namespaced provider API in the apiVersion string (.m.).
  - apiVersion: s3.aws.m.upbound.io/v1beta1
    kind: Bucket
    metadata:
      name: test-cp-backup-bucket
    spec:
      forProvider:
        region: us-east-1
  - apiVersion: kubernetes.m.crossplane.io/v1alpha1
    kind: Object
    metadata:
      name: test-cp-backup-config
    spec:
      forProvider:
        manifest:
          spec:
            objectStorage:
              credentials:
                source: InjectedIdentity
```

## Observed state (real example)

Feed a mocked `status` for an earlier resource and assert what renders from it. Keep
`validate: false`, as the scaffold does: `up test run` never reads it (up v0.55.0 source), so
`true` would check nothing (author-tests' `test-model.md`).

```yaml
apiVersion: meta.dev.upbound.io/v1alpha1
kind: CompositionTest
metadata:
  name: k8gb-lbcontroller-podidentity
spec:
  compositionPath: apis/ctp/composition.yaml
  xrdPath: apis/ctp/definition.yaml
  validate: false
  timeoutSeconds: 60
  xr:
    apiVersion: aws.platform.upbound.io/v1alpha1
    kind: ControlPlane
    metadata:
      name: test-cp
    spec:
      parameters:
        id: test-cp
        region: us-east-1
        version: "1.34"
        nodes: { count: 2, instanceType: t3.small }
        k8gb:
          enabled: "yes"
  observedResources:
  # Each mock: the composition-resource-name annotation, the name the render gave the resource,
  # and for a namespaced XR the XR's namespace - without it the mock is silently ignored
  # (charter/evidence.md, Coverage).
  # EKS cluster name/account come from the observed EKS XR status contract.
  - apiVersion: aws.platform.upbound.io/v1alpha1
    kind: EKS
    metadata:
      name: test-cp
      namespace: default
      annotations:
        crossplane.io/composition-resource-name: eks-cluster
    status:
      eks:
        clusterArn: arn:aws:eks:us-east-1:123456789012:cluster/test-cp-abc12345
  # Pod Identity association Ready -> controller scales up.
  - apiVersion: eks.aws.m.upbound.io/v1beta1
    kind: PodIdentityAssociation
    metadata:
      name: test-cp-lb-controller-pia
      namespace: default
      annotations:
        crossplane.io/composition-resource-name: lb-controller-pia
    status:
      conditions:
      - type: Ready
        status: "True"
  assertResources:
  - apiVersion: eks.aws.m.upbound.io/v1beta1
    kind: PodIdentityAssociation
    metadata:
      name: test-cp-lb-controller-pia
    spec:
      forProvider:
        clusterName: test-cp-abc12345
        serviceAccount: aws-load-balancer-controller
```

## E2E test (real example)

One `E2ETest` document per file. It tracks a channel with no pinned version, waits for `Ready`,
sizes the timeout to a real EKS cluster, and creates the `ClusterProviderConfig` every composed
resource defaults to.

```yaml
# tests/e2etest-controlplane/test.yaml
apiVersion: meta.dev.upbound.io/v1alpha1
kind: E2ETest
metadata:
  name: controlplane-with-backup
spec:
  crossplane:
    autoUpgrade:
      channel: Stable          # channel only - no pinned version
  defaultConditions:
  - Ready
  timeoutSeconds: 3600         # sized to EKS provisioning + UXP install
  cleanupTimeoutSeconds: 1200
  extraResources:
  - apiVersion: aws.m.upbound.io/v1beta1
    kind: ClusterProviderConfig  # cluster-scoped: no namespace; composed MRs default to it
    metadata:
      name: default
    spec:
      credentials:
        source: Upbound         # web identity on a Space; the credentials per target: author-tests' e2e.md
        upbound:
          webIdentity:
            roleARN: arn:aws:iam::123456789012:role/e2e-provider-aws
  manifests:
  - apiVersion: aws.platform.upbound.io/v1alpha1
    kind: ControlPlane
    metadata:
      name: e2e-test-cp
    spec:
      parameters:
        id: e2e-test-cp
        region: us-east-1
        version: "1.34"
        nodes: { count: 2, instanceType: t3.small }
        backup:
          enabled: "yes"
          location: arn:aws:s3:::upbound-e2e-test-cp-backup
  skipDelete: false
```

An `E2ETest` cannot assert a status field or a status condition beyond the `defaultConditions`
types (`Ready`), and those are condition types, not expressions: author-tests' `e2e.md` reference.
The Go and go-templating test references are [`go/tests.md`](go/tests.md) and
[`go-templating.md`](go-templating.md).
