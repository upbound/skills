# KCL: function structure

Module layout, the entry point, a domain module, and the helpers every resource uses. The KCL
index is [`../kcl.md`](../kcl.md); conditionals, comprehensions and references are in
[`patterns-logic.md`](patterns-logic.md).

## Module layout

```text
functions/<composition-name>/
├── main.k        # entry point: read the XR, build the config, call the modules
├── kcl.mod       # dependencies and module metadata
├── network.k     # one module per domain: VPCs, subnets, gateways
├── security.k    # security groups, policies
└── storage.k     # buckets, volumes
```

- `main.k` orchestrates and nothing else.
- One module per domain; private functions start with `_`.
- A single `main.k` is fine for a small function. Split when it grows.

## Entry point (`main.k`)

```kcl
import models.io.upbound.platform.myxrd.v1alpha1 as myxrd   # your XR: models.io.<reversed-group>.<version>
import regex
import network
import security
import storage

oxr = option("params").oxr      # observed composite resource
ocds = option("params").ocds    # observed composed resources, keyed by composition resource name
dxr = option("params").dxr      # desired composite resource
dcds = option("params").dcds    # desired composed resources

# The key every composed resource is stored under; Crossplane tracks the resource by it.
_metadata = lambda name: str -> any {
    { annotations = { "krm.kcl.dev/composition-resource-name" = name }}
}

# Kubernetes label values: at most 63 characters of alphanumerics and - _ ., beginning and
# ending with an alphanumeric. Replace every other character, cut, then trim what the cut left
# at either end ("-leading" becomes "leading", "a/b:c" becomes "a-b-c").
_labelValue = lambda v: str -> str {
    _cut = regex.replace(v, "[^A-Za-z0-9_.-]", "-")[:63]
    regex.replace(_cut, "^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "")
}
_sanitizeLabels = lambda tags: {str:str} -> {str:str} {
    {k: _labelValue(v) for k, v in tags}
}

# Typed access to the XR. A missing field is a type error here, not a runtime surprise.
_oxrMeta = myxrd.MyResource.metadata{**oxr.metadata}
_oxrSpec = myxrd.MyResource.spec{**oxr.spec}

# One config object for every module: fewer signatures, one place to change.
_config = {
    metadata = _metadata
    sanitizeLabels = _sanitizeLabels
    resourceName = _oxrMeta.name
    region = _oxrSpec.region
    cidrBlock = _oxrSpec.cidrBlock
    createVPC = _oxrSpec.createVPC if _oxrSpec.createVPC not in [None, Undefined] else True
    zones = _oxrSpec.zones or []
    tags = _oxrSpec.tags or {}
}

# items is the output, and a top-level name is immutable: never assign it twice.
items = network.generateNetworkResources(_config) \
    + security.generateSecurityResources(_config) \
    + storage.generateStorageResources(_config)
```

`items` is what function-kcl reads. Name every other top-level variable with a leading `_`:
reassigning a top-level name fails with `ImmutableError … Can not change the value of 'items',
because it was declared immutable`.

**An absent field is `Undefined`, not `None`** (measured with kcl 0.10.4, typed and untyped
access alike), so `x if x != None else default` never applies the default: it yields `Undefined`
and the field silently disappears. Test both, as `createVPC` does above. `x or default` is fine
where a falsy value may take the default (strings, lists, maps), never for a boolean.

## A domain module (`network.k`)

```kcl
"""Network resources: VPC, subnets, gateways."""
import models.io.upbound.awsm.ec2.v1beta1 as ec2v1beta1

_generateVPC = lambda config: {str: any} -> [any] {
    [
        ec2v1beta1.VPC{
            metadata = config.metadata("vpc") | {
                labels = config.sanitizeLabels(config.tags)
            }
            spec.forProvider = {
                region = config.region
                cidrBlock = config.cidrBlock
                enableDnsHostnames = True
                tags = config.tags | { Name = "vpc-${config.resourceName}" }
            }
        }
    ] if config.createVPC else []
}

# The public entry point main.k calls. Always returns a list, empty when nothing applies.
generateNetworkResources = lambda config: {str: any} -> [any] {
    _generateVPC(config) + _generateSubnets(config)
}
```

Every resource sets `forProvider` and nothing else unless the project asks
([charter §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)), and
merges `config.metadata("<key>")` into its metadata: the key is the composition resource name,
so it must be unique per resource and stable across runs (renaming it orphans the live resource).
Set `metadata.name` only when the resource needs a stable external name.

## Composing a connection Secret

A v2 XR publishes no connection details, so compose a Secret yourself
(`plan-v2-migration` `breaking-changes.md`, "Connection secrets"). No `metadata.namespace`: Crossplane
puts it in the XR's namespace
([charter §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)).

First, the resource whose details you read gets `writeConnectionSecretToRef`, beside its
`forProvider`; without it `ConnectionDetails` stays empty forever (charter §5):

```kcl
    metadata = config.metadata("db-instance")
    spec.forProvider = { ... }
    spec.writeConnectionSecretToRef.name = "${config.resourceName}-db-instance"
```

```kcl
import base64
import models.io.k8s.api.core.v1 as corev1

_connectionSecret = lambda config: {str: any} -> [any] {
    _db = ocds["db-instance"]
    _endpoint = _db?.Resource?.status?.atProvider?.endpoint
    # None until the provider has written the db-instance's connection Secret
    _password = _db?.ConnectionDetails?.password
    [
        corev1.Secret{
            metadata = config.metadata("connection-secret") | {
                name = "${config.resourceName}-connection"
            }
            data = {
                endpoint = base64.encode(_endpoint)   # status values are plain strings: encode them
                password = _password                  # ConnectionDetails values are already base64
            }
        }
    ] if _endpoint and _password else []   # never `or ""`: an empty password looks like success
}
```

The observed values exist only once the resource has been created and reported back, so the
Secret is gated on every value it carries, and appears on a later reconcile. A test reaches the
status branch only with `spec.observedResources`
([charter §8](../../../SKILL.md#8-a-green-run-is-not-evidence)), and never the connection
details: no render passes them, so assert `writeConnectionSecretToRef` on the `db-instance`
instead ([`charter/v2-resources.md`](../../charter/v2-resources.md)).
Importing `corev1` needs the Kubernetes API models: an `apiDependencies` entry in
`upbound.yaml` for `k8s`, then `up project build`.

