# KCL: pitfalls

KCL mistakes that render green, or fail in a way that does not name the cause. The KCL index is
[`../kcl.md`](../kcl.md). Entries marked "measured" were reproduced with kcl 0.10.4.

| Mistake | What happens | Fix |
|---|---|---|
| `x if x != None else default` on an absent field | the default never applies: an absent field is `Undefined`, not `None`, so the result is `Undefined` and the field disappears (measured) | `x if x not in [None, Undefined] else default` ([`patterns.md`](patterns.md#entry-point-maink)) |
| `if obj?.port` to include an optional field | a legitimate `0` or `False` is dropped (measured) | test against `[None, Undefined]` |
| A second top-level assignment to `items` (or any public name) | `ImmutableError … Can not change the value of 'items', because it was declared immutable` (measured) | prefix every intermediate with `_`; assign `items` once |
| A variable or lambda parameter named `rule` | `InvalidSyntax … expected one of ["identifier"]`: `rule` is a keyword (measured) | another name, e.g. `sgRule` |
| Import without the `m` (`models.io.upbound.aws.ec2…`, `models.io.crossplane.kubernetes…`) | renders the cluster-scoped `apiVersion` | `awsm`, `kubernetesm` ([`../kcl.md`](../kcl.md#imports-and-models)) |
| XR fields read from the raw dict | a misspelt field is `Undefined` at runtime instead of a type error | `myxrd.MyResource.spec{**oxr.spec}` |
| No `krm.kcl.dev/composition-resource-name` annotation | Crossplane cannot track the resource across runs | `metadata = config.metadata("<key>") \| {…}` on every resource; add annotations with `:` (next row) |
| `config.metadata("<key>") \| { annotations = {…} }` | `=` replaces the whole `annotations` dict, so the output loses `krm.kcl.dev/composition-resource-name` with no error, as if it had never been set (measured). A nested `res \| { metadata = { annotations: {…} } }` loses it the same way | `annotations: {…}`: `:` merges, and only a `:` at every level down to the key keeps what is already there. `labels = …` beside the annotation is safe: it is a different key |
| Renaming a composition resource name, or keying it on a list position that changes | the live resource is orphaned and a new one created | stable keys; see [`patterns-logic.md`](patterns-logic.md#list-comprehensions) |
| User tags copied into labels as they are | Kubernetes rejects the label value | `config.sanitizeLabels(config.tags)` |
| A hardcoded ID (`vpcId = "vpc-123"`) | breaks on every new environment | a selector ([`patterns-logic.md`](patterns-logic.md#references-between-composed-resources)) |
| `{Name = "x"} \| config.tags` | the user's tags overwrite the specific value | defaults first: `config.tags \| {Name = "x"}` |
| `providerConfigRef`, `managementPolicies` or `metadata.namespace` on a managed resource | a test asserting the same thing passes; the resource may never reconcile | `forProvider` only, unless the project asks ([charter §5](../../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs)) |
