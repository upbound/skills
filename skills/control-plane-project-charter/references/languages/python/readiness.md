# Python: observed resources, readiness and connection Secrets

- [Observed resources are keyed by composition resource name](#observed-resources-are-keyed-by-composition-resource-name)
- [Connection Secrets](#connection-secrets)
- [Mark a composed ProviderConfig ready](#mark-a-composed-providerconfig-ready)
- [Create on "ready or already exists", not on "ready"](#create-on-ready-or-already-exists-not-on-ready)
- [The early-return chain](#the-early-return-chain)
- [Reading the render](#reading-the-render)

The Python index is [`../python.md`](../python.md).

## Observed resources are keyed by composition resource name

`req.observed.resources` is keyed by the string you stored the resource under in
`rsp.desired.resources["KEY"]`, not by its generated name:

```python
if "mysql" in req.observed.resources:          # the key, not "mysql-myplatform-abc"
    observed = req.observed.resources["mysql"]
    mysql_mr = mysqlv1beta2.FlexibleServer(**resource.struct_to_dict(observed.resource))

    host = mysql_mr.status.atProvider.fqdn if mysql_mr.status and mysql_mr.status.atProvider else None
    # None until the provider writes the Secret this resource's writeConnectionSecretToRef names,
    # and always None without that reference (below)
    password = observed.connection_details.get("attribute.administrator_password")  # bytes
```

Values come from three places: `spec.forProvider` (what you set), `status.atProvider` (once the
cloud resource exists), and `connection_details` (provider-populated secrets, as bytes).

## Connection Secrets

A v2 XRD has no `connectionSecretKeys`, so a v2 XR does not publish connection details: compose a
Secret yourself (a v1 XR took them through `rsp.desired.composite.connection_details`).

Set `writeConnectionSecretToRef` beside `forProvider` on the resource you read them from
(charter §5):

```python
spec=mysqlv1beta2.Spec(
    forProvider=mysqlv1beta2.ForProvider(...),
    writeConnectionSecretToRef=mysqlv1beta2.WriteConnectionSecretToRef(
        name=f"{observed_xr.metadata.name}-mysql",   # in the XR's namespace: unique per XR
    ),
)
```

Then compose the Secret only once every value it carries is there:

```python
from crossplane.function import response
from models.io.k8s.api.core import v1 as corev1

host, password = None, None
if "mysql" in req.observed.resources:
    observed = req.observed.resources["mysql"]
    mysql_mr = mysqlv1beta2.FlexibleServer(**resource.struct_to_dict(observed.resource))
    if mysql_mr.status and mysql_mr.status.atProvider:
        host = mysql_mr.status.atProvider.fqdn
    password = observed.connection_details.get("attribute.administrator_password")

if host and password is not None:
    connection_secret = corev1.Secret(
        metadata=k8s.ObjectMeta(name=f"{observed_xr.metadata.name}-connection"),  # namespace: the XR's
        type="connection.crossplane.io/v1alpha1",
        stringData={"host": host, "password": password.decode()},  # plain text; Kubernetes encodes it
    )
    resource.update(rsp.desired.resources["connection-secret"], connection_secret)
elif "mysql" in req.observed.resources:
    # Never a default such as "": the Secret would look complete with an empty password.
    response.warning(rsp, "connection Secret not composed yet: mysql has no fqdn or no "
                          "attribute.administrator_password connection detail")
```

`connection_details` values are bytes: `.decode()` them for `stringData`, or base64-encode them
for `data`. The `k8s` core models (`models.io.k8s.api.core`) exist only with the `k8s` API
dependency in `upbound.yaml`, then `up project build`:

```yaml
spec:
  apiDependencies:
  - type: k8s
    k8s:
      version: v1.33.0
```

A test reaches this branch only with `observedResources`, and a password only as
[`charter/v2-resources.md`](../../charter/v2-resources.md) says; assert
`writeConnectionSecretToRef` on the composed `mysql` either way.

## Mark a composed ProviderConfig ready

A ProviderConfig the function composes (Helm, Kubernetes provider) has no `Ready` condition, so
function-auto-ready cannot judge it: mark it ready explicitly, or the XR never becomes ready.

```python
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

helm_provider_config = helmproviderv1beta1.ProviderConfig(
    metadata=k8s.ObjectMeta(name=f"{observed_xr.metadata.name}-helm"),  # unique per XR in the namespace
    spec=helmproviderv1beta1.Spec(
        credentials=helmproviderv1beta1.Credentials(
            source="Secret",
            secretRef=helmproviderv1beta1.SecretRef(
                name=f"{observed_xr.metadata.name}-kubeconfig",
                namespace=observed_xr.metadata.namespace,   # a spec value: the XR's namespace
                key="kubeconfig",
            ),
        ),
    ),
)
resource.update(rsp.desired.resources["helm-provider-config"], helm_provider_config)
rsp.desired.resources["helm-provider-config"].ready = fnv1.READY_TRUE
```

- The order relative to `resource.update()` does not matter: `update()` writes only
  `r.resource`, never `r.ready` (measured on function-sdk-python 0.11.0 and 0.5.0).
- The enum is `fnv1.READY_TRUE` (or `fnv1.Ready.READY_TRUE`). There is no
  `resource.READY_TRUE`; it raises `AttributeError` (function-sdk-python 0.11.0).
- A branch that sets readiness from observed state is reachable in a test that sets
  `observedResources` (charter §8; the syntax is in [`tests.md`](tests.md)).

## Create on "ready or already exists", not on "ready"

Creating a resource only while its dependency is `Ready` deletes it whenever the dependency flaps
(a restart, a reconcile), and the deletion cascades. Gate on ready *or* already observed:

```python
def resource_exists(req: fnv1.RunFunctionRequest, key: str) -> bool:
    return key in req.observed.resources

def is_resource_ready(req: fnv1.RunFunctionRequest, key: str) -> bool:
    observed = req.observed.resources.get(key)
    if not observed or not observed.resource:
        return False
    ready = resource.get_condition(observed.resource, "Ready")
    synced = resource.get_condition(observed.resource, "Synced")
    return ready.status == "True" and synced.status == "True"

resource.update(rsp.desired.resources["aks-cluster"], desired_aks)
if is_resource_ready(req, "aks-cluster") or resource_exists(req, "helm-release"):
    resource.update(rsp.desired.resources["helm-release"], helmproviderv1beta1.Release(...))
```

`if is_resource_ready(req, "aks-cluster"):` alone is the version that deletes the release.

## The early-return chain

Template functions are guard clauses:

```python
if "bucket" not in req.observed.resources:
    return                      # nothing observed yet
if "crossplane.io/external-name" not in observed_bucket.metadata.annotations:
    return                      # external name not assigned yet
if not params.versioning:
    return                      # versioning disabled
```

Anything appended at the end inherits every guard above it: a resource added after the
`versioning` check disappears whenever `versioning: false`, and no composition test that lacks a
`resourceRefs` guard notices. Give a new resource its own `if` block, above unrelated guards.

## Reading the render

How to get and read `render.log`, and what `--debug` prints, is in
[`charter/evidence.md`](../../charter/evidence.md). The Python-specific part: beside each test's `render.log`,
in the directory the run prints, is `<function>.log`, the function container's output, where a
Python traceback or `self.log` output lands.
