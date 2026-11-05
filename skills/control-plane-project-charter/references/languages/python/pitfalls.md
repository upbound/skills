# Python: pitfalls

The Python mistakes that give a green run and a broken platform, and the errors they print. The
Python index is [`../python.md`](../python.md).

## Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Import path derived by hand | `ModuleNotFoundError` | `python3 <author-composition>/scripts/probe_project.py --project <root> <Kind>` ([`imports.md`](imports.md)) |
| Non-namespaced model imported in a v2 project | renders the cluster-scoped `apiVersion` | the `.m.` path: `models.io.upbound.m.aws…`, not `models.io.upbound.aws…`. The probe script flags v1 modules |
| `.m.` in the wrong place | API not found | `azure.m.upbound.io`, not `azurem.upbound.io` (that is KCL's import segment) |
| Prefixed nested classes | `ResourceGroupSpec` / `VirtualNetworkForProvider` do not exist | classes are unprefixed and module-qualified: `rgv1beta1.Spec`, `rgv1beta1.ForProvider` |
| A keyword a provider model does not declare: a typo, or a field the Kind lacks (`tags` on a `Route`) | none: the models set no `extra`, so Pydantic drops it silently; the render lacks it | names from `probe_project.py --fields <Kind>` |
| No `struct_to_dict` | `AttributeError: get` at model construction | `resource.struct_to_dict(req.observed.composite.resource)` ([`patterns.md`](patterns.md#function-bootstrap)) |
| Several `resource.update(..., {"status": {...}})` calls | only the last field arrives; tests green | one call with all keys ([`patterns.md`](patterns.md#resourceupdate-replaces-nested-keys-it-does-not-merge-them)) |
| `xr.spec.<obj>.get(...)` or `.attr` on an optional XRD object | `'Kms' object has no attribute 'get'`, or `'dict' object has no attribute 'enableKeyRotation'` on half the inputs | drop `default: {}` from the XRD, or normalise ([`patterns.md`](patterns.md#an-optional-xrd-object-is-a-dict-when-absent-and-a-model-when-present)) |
| Fixed XRD `properties` for tags | `Input should be a valid string [input_value=None]` | `additionalProperties: {type: string}` ([`patterns.md`](patterns.md#tags-and-other-flexible-maps)) |
| `managementPolicies=["*"]`, a default `providerConfigRef`, or `metadata.namespace` on a managed resource | in the function: noise, or a reference to a ProviderConfig nothing creates; on an expected resource, a failed assertion where the render drops the default | omit them unless the project asks (charter §5); passed through: [`patterns.md`](patterns.md#building-a-managed-resource) |
| Composed ProviderConfig never marked ready | XR never becomes ready | `.ready = fnv1.READY_TRUE`, before or after `resource.update()`; there is no `resource.READY_TRUE` ([`readiness.md`](readiness.md#mark-a-composed-providerconfig-ready)) |
| Observed resource looked up by its generated name | `KeyError` or a silent miss | the composition key: `req.observed.resources["mysql"]` |
| Gated on `is_resource_ready` only | the resource is deleted when its dependency flaps | `or resource_exists(req, "key")` ([`readiness.md`](readiness.md)) |
| Resource appended after a guard clause | absent for some inputs | its own `if` block ([`readiness.md`](readiness.md#the-early-return-chain)) |
| Function converted to the other layout | build breaks on imports | match the project: embedded is `.model.` + `def compose(req, rsp)`, SDK is `models.` + `RunFunction` |

## Errors and what they mean

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for ResourceGroup
spec.forProvider.tags.Environment
  Input should be a valid string [input_value=None, input_type=NoneType]
```

The XRD declares tags with fixed `properties`. Use `additionalProperties: {type: string}`, then
`up project build` to regenerate the models.

```
ModuleNotFoundError: No module named 'models.io.example.platform.network.network'
```

The Kind segment is de-duplicated when the group's leftmost segment equals the lowercased Kind
(group `network.platform.example.io`, Kind `Network`): `from models.io.example.platform.network
import v1alpha1`. A sibling Kind in that group is not
(`models.io.example.platform.network.subnet`).

```
ModuleNotFoundError: No module named 'models'
```

`crossplane-models` is not installed: `.up/python` must exist (`up project build` or
`up dependency add`) and the `pyproject.toml` must list `crossplane-models @ file:...`. In the
embedded layout the models come from the `model` symlink, as `from .model.io...`.

```
AttributeError: 'Struct' object has no attribute 'spec'
```

`req.observed.composite.resource.spec` was read directly: parse it with
`resource.struct_to_dict()` first.

An expected resource reported as `no actual resource found`: read what rendered
([`charter/evidence.md`](../../charter/evidence.md)), then compare the name, the `apiVersion` and
any annotation the expectation names.

## Migrating a Python function from v1 to v2

The language-neutral v1 → v2 changes are in `plan-v2-migration`'s `breaking-changes.md`
reference. In Python they show up as the import (`models.io.upbound.<cloud>…`
→ `models.io.upbound.m.<cloud>…`), test `apiVersion`s gaining `.m.`, and connection details moving
from `rsp.desired.composite.connection_details` to a composed Secret
([`readiness.md`](readiness.md#connection-secrets)).
