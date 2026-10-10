# KCL

Everything KCL-specific for a control-plane project: composition functions and tests. The
language-agnostic rules are in [`control-plane-project-charter`](../../SKILL.md); this file and
[`kcl/`](kcl/) say how KCL expresses them.

| | |
|---|---|
| Scaffold a function | `up function generate <n> --language kcl` (always pass `--language`: the default is go-templating; KCL is the default only for `up test generate`) |
| Scaffold a test | `up test generate <n> --language kcl` (add `--e2e`) |
| Type-check a module | `kcl lint functions/<n>/` (exits 1 on a type error such as `x: int = "s"`) |
| Run a module | `kcl functions/<n>/main.k -D params='{"oxr": {...}}'`: without `-D params` it stops at `option("params").oxr` (`EvaluationError … invalid value 'NoneType' to load attribute 'oxr'`) |

## Where everything is

| File | What is in it |
|---|---|
| [`kcl/patterns.md`](kcl/patterns.md) | module layout, the entry point, a domain module, the helpers every resource uses, composing a connection Secret |
| [`kcl/patterns-logic.md`](kcl/patterns-logic.md) | conditional resources, list comprehensions, selector references, merging, optional fields, multi-branch logic |
| [`kcl/tests.md`](kcl/tests.md) | composition and E2E test templates, and multi-test layouts |
| [`kcl/pitfalls.md`](kcl/pitfalls.md) | KCL mistakes that render green and break later |

## Imports and models

**KCL puts the `.m.` on the cloud segment:** `awsm`, `azurem`, `gcpm`, `kubernetesm`. Python
puts it before the cloud (`models.io.upbound.m.aws`). The import without the `m` is the
cluster-scoped API, for v1 projects only
([charter §5](../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)).

```kcl
import models.io.upbound.awsm.ec2.v1beta1 as ec2v1beta1           # not models.io.upbound.aws.ec2…
import models.io.upbound.awsm.v1beta1 as awsmv1beta1              # ClusterProviderConfig, ProviderConfig
import models.io.upbound.azurem.network.v1beta1 as networkv1beta1
import models.io.upbound.gcpm.compute.v1beta1 as computev1beta1
import models.io.crossplane.kubernetesm.v1alpha1 as k8sobjv1alpha1  # provider-kubernetes Object
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1         # CompositionTest, E2ETest
import models.io.k8s.api.core.v1 as corev1                          # Secret, ConfigMap
import models.k8s.apimachinery.pkg.apis.meta.v1 as metav1           # ObjectMeta (not under models.io)
```

Your own XR's models are under `models.io.<reversed-group>.<version>`: group
`aws.platform.upbound.io` is `models.io.upbound.platform.aws.v1alpha1`.
