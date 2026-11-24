# Python: import paths

The Python index is [`../python.md`](../python.md).

## Resolve it, do not derive it

One command prints the project's layout, its import prefix, the exact import line and the
model's class names, and flags non-namespaced (v1) provider modules and Kinds defined in more
than one API group:

```bash
python3 <author-composition>/scripts/probe_project.py --project <project-root> Bucket StorageBucket
# functions/compose-bucket  layout=embedded  import prefix='.model.'
# Bucket:
#     from .model.io.upbound.m.aws.s3.bucket import v1beta1  <- USE THIS
#       classes (module-qualified, UNPREFIXED): ForProvider, ProviderConfigRef, Spec, Rule, ...
```

## The rule behind it

One rule for XRs and managed resources alike: reverse the API group, then append the lowercased
Kind, **unless the group's leftmost segment already equals it**. After reversal that segment is
the last in the path, which is what up's generator compares against the Kind
(`internal/schemas/generator/python.go`). The version is the module.

| API group + Kind | Model module | |
|---|---|---|
| `platform.example.com` + `StorageBucket` | `com/example/platform/storagebucket/v1alpha1` | Kind appended |
| `s3.aws.m.upbound.io` + `Bucket` | `io/upbound/m/aws/s3/bucket/v1beta1` | Kind appended |
| `azure.m.upbound.io` + `ResourceGroup` | `io/upbound/m/azure/resourcegroup/v1beta1` | Kind appended (observed) |
| `aws.platform.upbound.io` + `Network` | `io/upbound/platform/aws/network/v1alpha1` | Kind appended (observed) |
| `network.platform.example.io` + `Subnet` | `io/example/platform/network/subnet/v1alpha1` | Kind appended |
| `network.platform.example.io` + `Network` | `io/example/platform/network/v1alpha1` | **de-duplicated** |

That de-duplication is the trap: it makes one Kind look "group-level" and its sibling Kinds in
the same group look different. Do not generalize from one example; run the script.

```python
from models.com.example.platform.storagebucket import v1alpha1                     # XR
from models.io.example.platform.network import v1alpha1 as networkv1alpha1         # XR, de-duplicated
from models.io.upbound.m.aws.s3.bucket import v1beta1 as bucketv1beta1             # MR
from models.io.upbound.m.azure.network.virtualnetwork import v1beta1 as vnetv1beta1
from models.io.k8s.api.core import v1 as corev1                                    # Secret
from models.io.k8s.apimachinery.pkg.apis.meta import v1 as k8s                     # ObjectMeta
```

In the embedded layout the paths are identical with the `.model.` prefix:
`from .model.com.example.platform.storagebucket import v1alpha1`.

**Classes inside a module are unprefixed** and module-qualified: `rgv1beta1.Spec`,
`rgv1beta1.ForProvider`, `rgv1beta1.ProviderConfigRef`, never `ResourceGroupSpec`. A `.m.`
provider model sits in `io/upbound/m/<provider>/…`; the non-`.m.` twin in
`io/upbound/<provider>/…` is the cluster-scoped API, for v1 projects only.

Without the script:

```bash
find .up/python/models -type d -name storagebucket         # -> com/example/platform/storagebucket
grep '^class ' .up/python/models/com/example/platform/storagebucket/v1alpha1.py
```
