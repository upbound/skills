# Python: composition function patterns

The function bootstrap, building a managed resource, and the Python-specific data-shape traps:
tag maps, `resource.update()` semantics, a Fatal result, optional XRD objects, namespaces, and
XRD schemas that generate clean models. The Python index is [`../python.md`](../python.md).

## Function bootstrap

The SDK function is a gRPC `FunctionRunner` class. Parse the observed XR with `struct_to_dict`
first, right after `rsp = response.to(req)`:

```python
# functions/network/function/fn.py
import grpc
from crossplane.function import logging, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as grpcv1

from models.io.k8s.apimachinery.pkg.apis.meta import v1 as k8s
from models.io.upbound.m.azure.resourcegroup import v1beta1 as rgv1beta1
from models.io.example.platform.network import v1alpha1 as networkv1alpha1


class FunctionRunner(grpcv1.FunctionRunnerService):
    """A FunctionRunner handles gRPC RunFunctionRequests."""

    def __init__(self):
        self.log = logging.get_logger()

    async def RunFunction(
        self, req: fnv1.RunFunctionRequest, _: grpc.aio.ServicerContext
    ) -> fnv1.RunFunctionResponse:
        rsp = response.to(req)
        observed_xr = networkv1alpha1.Network(
            **resource.struct_to_dict(req.observed.composite.resource)
        )
        location = observed_xr.spec.location
        tags = dict(observed_xr.spec.tags) if observed_xr.spec.tags else {}
        # ...build managed resources, resource.update(...), then:
        return rsp
```

**Why `struct_to_dict`:** `req.observed.composite.resource` is a `google.protobuf.Struct` in
every SDK version. `Kind(**req.observed.composite.resource)` unpacks the top level, but the
nested values are still `Struct`, and Pydantic fails at construction with an unhelpful message:

```
AttributeError: get
```

The other, `'Struct' object has no attribute 'spec'`, comes from reading
`req.observed.composite.resource.spec` directly.

In the embedded layout the same body lives in `def compose(req, rsp):` in
`functions/<n>/main.py`: no class, `rsp` is a parameter (no `response.to`), and imports use the
`.model.` prefix.

## Building a managed resource

Set `forProvider` and nothing else unless the project asks for more
([`control-plane-project-charter` §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)):

```python
desired_rg = rgv1beta1.ResourceGroup(
    spec=rgv1beta1.Spec(
        forProvider=rgv1beta1.ForProvider(location=location, tags=tags),
    ),
)
resource.update(rsp.desired.resources["rg"], desired_rg)   # the key is the composition resource name
```

Two things are Python-specific:

- **`ProviderConfigRef` requires `kind`** in the Pydantic model. That constrains constructing
  one when the project asks for it; it is not a reason to construct one.
- **What reaches the render depends on the SDK's serializer** ([`../python.md`](../python.md#set-up-the-venv-first)).
  From 0.13.0 (`exclude_unset`) every field you set explicitly is emitted, including one set to
  its default, such as `managementPolicies=["*"]`. Up to 0.12.0 (`exclude_defaults`) a value
  equal to the model default is dropped. Either way: do not set what the CRD defaults.

## Tags and other flexible maps

What you get depends on how the XRD declared the field. With `additionalProperties: {type:
string}`, codegen emits `tags: Optional[Dict[str, str]] = None`: already a plain dict, and
`dict(...)` is a harmless no-op. With fixed `properties`, codegen emits a model class whose
missing keys are `None`, and a downstream model fails with
`Input should be a valid string [input_value=None]`. Fix that in the XRD, not in the function:

```yaml
tags:                       # flexible map: generates Dict[str, str]
  type: object
  additionalProperties:
    type: string
```

```python
# Correct under either schema:
tags = {**(dict(observed_xr.spec.tags) if observed_xr.spec.tags else {}), "ManagedBy": "crossplane"}
```

Use fixed `properties` only when every key is known. Everything else about the XR's schema
(descriptions, enums, bounds, immutability, `status`) is in
[`charter/xrd-design.md`](../../charter/xrd-design.md), and the v2 XRD skeleton in
[`charter/v2-resources.md`](../../charter/v2-resources.md).

## `resource.update()` replaces nested keys; it does not merge them

`resource.update()` delegates to protobuf `Struct.update`, which clears a sub-struct before
writing a nested dict:

```python
from google.protobuf.struct_pb2 import Struct
s = Struct()
s.update({"status": {"a": 1}})
s.update({"status": {"b": 2}})
# -> {'status': {'b': 2.0}}      'a' is gone
```

So several status writes keep only the last, and also wipe `status.conditions`:

```python
# Wrong: three of these four writes are discarded
resource.update(rsp.desired.composite, {"status": {"kmsKeyArn": arn}})
resource.update(rsp.desired.composite, {"status": {"kmsKeyId": key_id}})
resource.update(rsp.desired.composite, {"status": {"tableName": name}})
resource.update(rsp.desired.composite, {"status": {"tableArn": table_arn}})

# Right: one call, one dict
resource.update(rsp.desired.composite, {"status": {
    "kmsKeyArn": arn, "kmsKeyId": key_id, "tableName": name, "tableArn": table_arn,
}})
```

Nothing crashes and the suite stays green; the XR reports three outputs as absent. Assert
every status field on the composite ([`tests.md`](tests.md)).

The same holds for `metadata`: `resource.update(r, {"metadata": {"annotations": {...}}})` on a
resource already written drops the labels the model set. Put annotations on the model's
`ObjectMeta` before the first `update`, or mutate in place:
`r.resource.get_or_create_struct("metadata").get_or_create_struct("annotations")[key] = value`
(a `Struct` has no `setdefault`).

## A Fatal result

```python
if unknown:
    response.fatal(rsp, f"unknown externalNames key(s): {', '.join(unknown)}")
    return rsp
```

`response.fatal` only appends a result with `SEVERITY_FATAL`; it neither stops the function nor
clears `rsp.desired` (function-sdk-python 0.11.0). Return right after it. Crossplane applies nothing
from a Fatal response, but a unit test reads `rsp` as built, so validate before the first
`resource.update` if the test asserts that nothing was composed. `response.to(req)` copies the
request's tag, desired state and context into `rsp`. The test is in
[`tests.md`](tests.md#function-unit-tests).

## An optional XRD object is a `dict` when absent and a model when present

**Check the generated declaration first; this applies to one case only.** The model is in
`.up/python/models/<reversed-group>/<kind>/<version>.py` (`probe_project.py --fields` shows an
XR's spec one level deep).

| Generated declaration | What you get | How to read it |
|---|---|---|
| `kms: Optional[Kms] = {}` | `dict` when absent, `Kms` when set | normalise first (below) |
| `kms: Optional[Kms] = None` | `None` when absent, `Kms` when set | `xr.spec.kms.field if xr.spec.kms else <default>` |
| `rules: Optional[List[Rule]] = None` | `None` when absent, `list[Rule]` when set | `for r in (xr.spec.rules or []): r.prefix` |

A nested XRD object with `default: {}` generates `Optional[Kms] = {}`, and Pydantic does not
validate or coerce defaults, so no single access style works:

```python
Spec().kms                                 # -> {}        <class 'dict'>
Spec(kms={"enableKeyRotation": False}).kms # -> Kms(...)   <class 'Kms'>

cfg = xr.spec.kms or {}
cfg.get("enableKeyRotation", True)   # crashes when the field IS set   (Kms has no .get)
cfg.enableKeyRotation                # crashes when the field is ABSENT (dict has no attr)
```

Fix it in one of two places:

1. **In the XRD, preferably:** drop `default: {}` from object-typed properties. It buys
   nothing: the API server and `up test run` apply nested defaults once the object exists.
2. **In the function**, if the XRD must keep it, normalise before reading:
   ```python
   raw = xr.spec.kms
   kms = raw if isinstance(raw, xrv1alpha1.Kms) else xrv1alpha1.Kms(**(raw or {}))
   rotation = kms.enableKeyRotation if kms.enableKeyRotation is not None else True
   ```

It bites only where nothing applies the XRD: `up test run` without `xrdPath`, bare
`crossplane render`, and `run_function.py`. With `xrdPath` set, and on a real API server, the
`{}` becomes a model before the function runs, so a minimal-XR test does not catch it. Only a
test with `xrdPath` deliberately unset proves the guard; if every test sets `xrdPath`, the guard
is dead code.

None of this applies to a typed field, and defending against it anyway is dead code:
`hasattr` on a Pydantic field is always `True`, and `isinstance(x, dict)` on a typed list element
is always `False`. Keep dict handling for genuinely untyped input: `struct_to_dict()` output,
`context`, and the `= {}` case above.

## Namespaces

With a namespaced XR, Crossplane overwrites `metadata.namespace` on every composed resource
(managed resources, Secrets, ConfigMaps, child XRs) with the XR's namespace, so do not set it
([charter §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)). You
need the XR's namespace only for values inside a resource's spec, such as a ProviderConfig's
`secretRef.namespace` ([`readiness.md`](readiness.md)) or the manifest of a provider-kubernetes
`Object`:

```python
parent_ns = observed_xr.metadata.namespace   # for spec values only, never for metadata.namespace
```

A cluster-scoped XR is the exception: there, the function chooses the namespace.
