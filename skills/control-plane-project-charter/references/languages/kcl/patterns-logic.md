# KCL: conditionals, comprehensions and references

Structure and the helpers (`config.metadata`, `config.sanitizeLabels`) are
in [`patterns.md`](patterns.md); the KCL index is [`../kcl.md`](../kcl.md).

## Conditional resources

A generator returns a list, and an empty one when the condition does not hold: end the
expression with `else []`, so the `+` that joins generators always gets a list. (Without an
`else`, the line does not parse.)

```kcl
_generateGateway = lambda config: {str: any} -> [any] {
    [
        ec2v1beta1.InternetGateway{
            metadata = config.metadata("igw")
            spec.forProvider = {
                region = config.region
                vpcIdSelector.matchControllerRef = True
                tags = config.tags | { Name = "igw-${config.resourceName}" }
            }
        }
    ] if config.createGateway and len(config.zones) > 0 else []
}
```

## List comprehensions

Iterate with an index so each resource gets its own composition resource name, and distribute
over zones round-robin with a modulo:

```kcl
_generateSubnets = lambda config: {str: any} -> [any] {
    [
        ec2v1beta1.Subnet{
            metadata = config.metadata("subnet-${i}") | {
                labels = config.sanitizeLabels(config.tags) | {
                    "zone": config.zones[i % len(config.zones)]
                    "index": str(i)
                }
            }
            spec.forProvider = {
                region = config.region
                availabilityZone = config.zones[i % len(config.zones)]
                cidrBlock = cidr
                vpcIdSelector.matchControllerRef = True
            }
        }
        for i, cidr in config.subnetCidrs
    ] if len(config.subnetCidrs) > 0 and len(config.zones) > 0 else []
}
```

The labels are what a sibling selects on (below). Keep the index stable: it is part of the
composition resource name, so reordering the input list renames, and so deletes, live resources.

## References between composed resources

Reference a sibling with a selector, never with a hardcoded ID; the provider resolves it once
the target exists, so the function stays single-pass.

| Selector | Matches |
|---|---|
| `matchControllerRef = True` | resources composed by the same XR |
| `matchLabels = {...}` | resources carrying those labels |
| both | labelled resources of the same XR, the usual way to pick one of several |

```kcl
_generateRouteTableAssociations = lambda config: {str: any} -> [any] {
    [
        ec2v1beta1.RouteTableAssociation{
            metadata = config.metadata("rta-${i}")
            spec.forProvider = {
                region = config.region
                routeTableIdSelector.matchControllerRef = True
                subnetIdSelector = {
                    matchControllerRef = True
                    matchLabels = { "zone": config.zones[i], "index": str(i) }
                }
            }
        }
        for i in range(len(config.zones))
    ]
}
```

## Merging with `|`

The right-hand side wins, so put defaults first and the specific values last:

```kcl
tags = config.baseTags | config.resourceTypeTags | { Name = "rt-${config.resourceName}" }
```

## Optional fields

An absent field reads as `Undefined`, not `None` ([`patterns.md`](patterns.md#entry-point-maink)),
so test both before falling back to a default, and use `?.` to read through a missing parent:

```kcl
retention = _oxrSpec.retentionDays if _oxrSpec.retentionDays not in [None, Undefined] else 7
prefix = config.lifecycle?.prefix       # None if lifecycle is absent; no error
```

To leave an optional field out of the rendered resource instead of writing a placeholder, merge
it in conditionally:

```kcl
spec.forProvider = {
    type = sgRule.type
    cidrBlocks = sgRule.cidrBlocks
    region = config.region
    securityGroupIdSelector.matchControllerRef = True
} | ({fromPort = sgRule.fromPort} if sgRule?.fromPort else {}) \
  | ({toPort = sgRule.toPort} if sgRule?.toPort else {}) \
  | ({protocol = sgRule.protocol} if sgRule?.protocol else {})
```

`if sgRule?.fromPort` drops a legitimate `0` (measured): test against `[None, Undefined]` where
zero or `False` is a valid value. `rule` is a KCL keyword, so no variable can be called that.

## Multi-branch logic

Two strategies fit in one expression:

```kcl
_generateNodes = lambda config: {str: any} -> [any] {
    [
        Provider.Resource{
            metadata = config.metadata("node-${i}")
            spec.forProvider = { zone = config.zones[i], region = config.region }
        }
        for i in range(len(config.zones))
    ] if config.strategy == "distributed" else [
        Provider.Resource{
            metadata = config.metadata("node-shared")
            spec.forProvider = { zone = config.zones[0], region = config.region }
        }
    ] if config.strategy == "shared" and len(config.zones) > 0 else []
}
```

With three or more interacting conditions, build the list imperatively inside the lambda:

```kcl
_generateResources = lambda config: {str: any} -> [any] {
    resources = []
    if config.enableFeature1:
        resources += [Provider.ResourceType1{
            metadata = config.metadata("type1")
            spec.forProvider.region = config.region
        }]
    if config.enableFeature2 and config.strategy == "distributed":
        resources += [Provider.ResourceType2{
            metadata = config.metadata("type2-${i}")
            spec.forProvider = { zone = config.zones[i], region = config.region }
        } for i in range(len(config.zones))]
    resources
}
```
