# Crossplane v2 resources: the detail

- [The `.m.` API groups](#the-m-api-groups)
- [The verified behaviour behind §5's field table](#the-verified-behaviour-behind-5s-field-table)
- [Authoring the XRD](#authoring-the-xrd)
- [What the CRD defaults do to a render](#what-the-crd-defaults-do-to-a-render)
- [What the function returns for the XR](#what-the-function-returns-for-the-xr)
- [Connection details reach a function only through `writeConnectionSecretToRef`](#connection-details-reach-a-function-only-through-writeconnectionsecrettoref)
- [Choosing a ProviderConfig](#choosing-a-providerconfig)
- [Symptom of a missing or wrong ProviderConfig](#symptom-of-a-missing-or-wrong-providerconfig)
- [Grep your own function before you report](#grep-your-own-function-before-you-report)

[`control-plane-project-charter` §5](../../SKILL.md#5-crossplane-v2-what-a-composed-resource-actually-needs) states the rules.

---

## The `.m.` API groups

**`.m.` is for *modern*, not "naMespaced"** (Crossplane's upgrade guide: "The `.m.` indicates
modern namespaced managed resources"). The groups hold the namespaced managed resources *and*
the cluster-scoped `ClusterProviderConfig` they default to, in the bare `aws.m.upbound.io` — so
the "namespaced" reading cannot be right.

---

## The verified behaviour behind §5's field table

| Field | Verified behaviour |
|---|---|
| `metadata.namespace` | **If the XR is namespaced**, Crossplane overwrites it with the XR's namespace (`if xr.GetNamespace() != "" { cd.SetNamespace(...) }`), so a function setting a *different* namespace is silently overridden, not merged with. A **cluster-scoped** XR is the exception — its composed resources keep the namespace the function sets, which is how a cluster XR targets one. (A namespaced XR composing a cluster-scoped kind is a hard error, not a namespace question.) |
| `managementPolicies` | The namespaced MR spec carries `+kubebuilder:default={"*"}`, so the API server fills it in, and that default deletes the external resource with the MR. Never write `["*"]` yourself. Set it only for a different policy — `["Create","Observe","Update","LateInitialize"]` to orphan on delete — or when the project's API exposes it as a parameter. |
| `deletionPolicy` | The namespaced MR spec has no such field. To orphan, use `managementPolicies` (above); to delete, set nothing. A v1 API's `deletionPolicy` parameter maps the same way (`plan-v2-migration`). |
| `providerConfigRef` | The same struct, the same way: `+kubebuilder:default={"kind":"ClusterProviderConfig","name":"default"}`. |
| `metadata.name` | Unless set, Crossplane generates `<prefix>-<sha256(xr-uid + composition-resource-name)[:12]>`, where the prefix comes from the `crossplane.io/composite` label, truncated to 63 chars. Deterministic for one XR instance, **not** across re-creations — and it falls back to a random 5-char suffix when the composition-resource-name annotation or the controller ownerRef is missing. Inside a *render* it is fully deterministic and safe to assert — see [`evidence.md`](evidence.md). |

---

## Authoring the XRD

The same API, inferred versus written, in the model `up project build` generates:

| | inferred from an example | written directly |
|---|---|---|
| a required field | `Optional[str] = None` | `region: str` |
| `retentionDays: 90` | `Optional[float] = None` — no default, and `number` not `integer` | `Optional[int] = 90` |
| `tags: {team: platform}` | fixed properties, one per key the example happened to use | `Optional[Dict[str, str]]` |
| `status` | absent | modelled |

`up project build` generates the models from whatever XRD is on disk, so a hand-written one
needs no extra step.

The skeleton for a **new** API. Every line matters for v2, and the cloud project templates,
being v1, do not show it ([`generators.md`](generators.md)):

```yaml
apiVersion: apiextensions.crossplane.io/v2      # v2, and there is still no v2 Composition
kind: CompositeResourceDefinition
metadata:
  name: storagebuckets.platform.example.com     # <plural>.<group>
spec:
  scope: Namespaced                             # v2 replaces claimNames; do not write claimNames
  group: platform.example.com
  names:
    kind: StorageBucket                         # no X prefix on a new API
    plural: storagebuckets
  versions:
  - name: v1alpha1
    served: true
    referenceable: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              region: {type: string, description: Region to create the bucket in}
              retentionDays: {type: integer, default: 90, description: Days to keep objects}
              tags:                              # an open-ended map, not fixed properties
                type: object
                description: Tags applied to the bucket
                additionalProperties: {type: string}
            required: [region]
          status:                                # model it, or your function cannot report
            type: object
            properties:
              bucketArn: {type: string, description: The bucket's cloud identifier}
```

The fields sit directly under `spec` here, as in the function templates (`xr.Spec.Region` in
Go). Nesting them under `spec.parameters`, as many existing APIs do, is equally valid: the
project's spec and its existing XRDs decide, and the function and the tests follow the XRD.

An existing v1 API keeps its Kind when migrated, `X` prefix included: a new Kind is a new API
([`xrd-design.md`](xrd-design.md)).

Keep writing the example XR first: it is the render input for tests, and drafting the API a
user will write keeps the schema honest. Do not derive the schema from it.

The import or type path that reaches these APIs is language-specific: see
[`languages/`](../languages/). Run `up project build` after a provider version change to
regenerate models.

---

## What the CRD defaults do to a render

`managementPolicies` and `providerConfigRef` are CRD schema defaults. `up test run` and
`crossplane render` have no API server, so no CRD defaulting happens at render time, and what a
render shows depends on two things: what `up`'s schema generator bakes into the model, and what
the language's serializer emits.

| Models | `managementPolicies` | `providerConfigRef` | Reaches the render? |
|---|---|---|---|
| Python | materialized (`= ['*']`) | materialized (`default_factory`) | **No** from a model, under the pinned SDK even when assigned ([`patterns.md`](../languages/python/patterns.md#building-a-managed-resource)) |
| KCL | materialized (`= ["*"]`) | not materialized | `managementPolicies` yes |
| Go | not materialized | not materialized | no |

So a rendered Python model shows neither, and a KCL render shows `managementPolicies`. Both are
correct, and neither tells you what the API server fills in on a real control plane. Never
"fix" a function because a render shows or omits them, and add them to an *expected* resource
only where the function sets them and its render carries them: an expected field the render
omits fails the assertion.

Both fields come from the same place: the embedded `ManagedResourceSpec` struct in
crossplane-apis v2 (`core/v2/resource_namespace.go`), which every namespaced provider MR inlines.

---

## What the function returns for the XR

Each pipeline run starts from empty desired state, and Crossplane applies the XR status it
returns with server-side apply (`composition_functions.go`, v2.4.3):

- **A key the pipeline stops writing is removed.** Clear nothing yourself.
- **Never write `null`:** the API server rejects it for a typed field, and the XR gets no status.
- **A render keeps the input XR's status keys the function didn't write** (up v0.55.1).
- **Custom conditions go in the response's conditions** (the language file), not desired
  `status.conditions`, where Crossplane's copy of the current ones freezes them at their first
  value. Returned `Ready`, `Synced`, `Healthy`, `UpToDate` are ignored.

---

## Connection details reach a function only through `writeConnectionSecretToRef`

The behaviour behind §5's rule, from the Crossplane v2.2 source:

- **Crossplane reads them from the Secret the composed resource names, and from nowhere else.**
  For each observed composed resource it calls `SecretConnectionDetailsFetcher.FetchConnection`
  (`internal/controller/apiextensions/composite/connection.go`): no `writeConnectionSecretToRef`
  returns nothing, and a Secret the provider has not written yet is ignored (`NotFound`). Both
  reach the function as an empty map, with no error and no event.
- **A lookup in that map then yields nothing, silently:** KCL `?.ConnectionDetails?.password`
  is `None` (kcl 0.10.4), Python `connection_details.get(…)` is `None`, a Go map read is `nil`.
- **On a namespaced MR the reference has only `name`.** The provider writes the Secret into the
  MR's namespace, which is the XR's, so name it per XR (`<xr-name>-<composition-key>`): a fixed
  name collides between two XRs in one namespace.
- **A render passes them only when the test supplies them.** up v0.55.0 renders with Crossplane
  v2.3, which runs the same fetcher over the test's inputs: an observed mock that sets
  `writeConnectionSecretToRef`, plus that Secret (in the mock's namespace) in `extraResources`,
  reaches the function as its connection details. The test writes the mock's reference and the
  Secret's keys, so also assert that the composed resource sets `writeConnectionSecretToRef` (that
  is the regression a render can see) and that no connection Secret is composed while the details
  are missing. Whether the provider writes those key names stays unverified until a control plane.

**On a control plane**, a missing reference or a wrong key name looks the same: the managed
resource reaches `Ready`, and the connection Secret the function composes never appears (the XR
can be `Ready` without it, since it was never desired). Check, without printing a value:

```bash
kubectl get <kind> <name> -n <ns> -o jsonpath='{.spec.writeConnectionSecretToRef}'   # set?
kubectl get secret <that-name> -n <ns> -o json | jq '.data | keys'                    # key names only
```

---

## Choosing a ProviderConfig

**Omit `providerConfigRef` if and only if `ClusterProviderConfig/default` exists and is the
right one.** That is the common case. Otherwise set it — when the platform has several
credentials, when its single `ClusterProviderConfig` is not named `default` (omitting the
reference there leaves every resource unreconciled), and when the project's spec or API sets
one. Then make `kind` match an object that exists:

| `kind` | Selects | When |
|---|---|---|
| `ClusterProviderConfig` | cluster-scoped config, shared by all namespaces | the v2 default; name it explicitly to pick a non-`default` one |
| `ProviderConfig` | namespaced config in the resource's namespace | per-namespace credentials — **only if a `ProviderConfig` of that name exists in, or is created in, the XR's namespace** |

Do not set `kind: ProviderConfig` because you found it elsewhere:

- **The cloud project templates use `kind: ProviderConfig`** — in E2E tests and in
  `examples/providerconfig.yaml`. They are Crossplane **v1** projects, where `ProviderConfig` is
  the cluster-scoped kind. They are no v2 precedent.
- **`up test generate --e2e` creates no ProviderConfig at all** — it emits `extraResources: []`
  in every language. If a test needs one, you add it (author-tests' `e2e.md` reference).

Some languages make `kind` a *required* field when you construct a `providerConfigRef`
object. That constrains constructing the object; it is no reason to construct it.

---

## Symptom of a missing or wrong ProviderConfig

The composition suite passes either way; only a control plane shows it. Read the managed
resource with `kubectl describe <kind> <name> -n <ns>` — conditions **and** events:

| You see | It means |
|---|---|
| `Synced=False` and a `CannotConnectToProvider` warning event (`cannot get referenced ProviderConfig …` from Upbound providers) | the reference names a ProviderConfig that does not exist, or the wrong `kind`. Check with `kubectl get clusterproviderconfig,providerconfig -A`. A missing *namespaced* one may show nothing at all (last row) |
| blank conditions | observed but not reconciled yet. Wait, then read it again |
| no conditions and no events, for minutes | either nothing is reconciling the kind — the provider is not installed or not healthy (`kubectl get providers.pkg.crossplane.io`, `INSTALLED` and `HEALTHY`), its pod is not running, or the MR's CRD is not established (`kubectl get crd <plural>.<group>`) — or the MR references a namespaced `ProviderConfig` that does not exist in its namespace. Observed with provider-aws-ec2 v2.8.2 on kind: MRs silent for 20 min, and creating the missing `ProviderConfig` got them reconciled within 16 s. Compare the MR's `providerConfigRef` with `kubectl get providerconfig -n <ns>` |

---

## Grep your own function before you report

Two checks, because one regex cannot do both:

```bash
# 1. The two fields that are not hardcoded on a managed resource unless the project sets them.
grep -rniE 'providerConfigRef|managementPolicies' functions/

# 2. An assignment to a namespace field — not the word "namespace", which appears in
#    every honest comment explaining why the field is deliberately absent.
grep -rniE '(metadata\.)?namespace\s*[:=]' functions/
```

"No output" is not the pass condition: a well-commented function mentions these fields. Judge
each hit: a hardcoded value on a managed resource is a defect; a parameterised, deliberate
opt-in, or a value the project's spec requires, is not (§5). Legitimate namespace hits are a
cluster-scoped XR choosing one, and objects embedded inside `forProvider`, such as a
provider-kubernetes `Object` manifest. `grep -r` does not follow the `model` symlink into the
generated schemas — keep it that way, or the output is thousands of lines.
