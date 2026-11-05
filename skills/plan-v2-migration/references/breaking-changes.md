# Crossplane v1 → v2: the breaking changes

- [Summary](#summary)
- [Project file](#project-file)
- [XRD](#xrd)
- [Kind and the X prefix](#kind-and-the-x-prefix)
- [Provider API groups](#provider-api-groups)
- [deletionPolicy](#deletionpolicy)
- [providerConfigRef](#providerconfigref)
- [Secret references](#secret-references)
- [Connection secrets](#connection-secrets)
- [Composition](#composition)
- [Examples](#examples)
- [Tests](#tests)
- [Directory and function names](#directory-and-function-names)
- [Installed v1 APIs](#installed-v1-apis)

What changes when a v1 control-plane project moves to Crossplane v2, in language-neutral YAML.
How a function or test spells it (import paths, model types, the XR bootstrap) is in the
project's language file in the charter —
`control-plane-project-charter/references/languages/README.md` says which one. The rules for a v2
composed resource are `control-plane-project-charter` §5; this file maps v1 onto them.

## Summary

| Area | v1 | v2 | Section |
|---|---|---|---|
| `upbound.yaml` | `meta.dev.upbound.io/v1alpha1` | `meta.dev.upbound.io/v2alpha1` | [Project file](#project-file) |
| XRD `apiVersion` | `apiextensions.crossplane.io/v1` | `apiextensions.crossplane.io/v2` | [XRD](#xrd) |
| XRD `spec.scope` | absent (= `LegacyCluster`) | `Namespaced` | [XRD](#xrd) |
| `claimNames`, `connectionSecretKeys`, `defaultCompositeDeletePolicy` | allowed | removed | [XRD](#xrd) |
| XR Kind (`XNetwork`) | X prefix by convention | unchanged by default | [Kind and the X prefix](#kind-and-the-x-prefix) |
| Managed resource `apiVersion` | `ec2.aws.upbound.io/v1beta1` | `ec2.aws.m.upbound.io/v1beta1` | [Provider API groups](#provider-api-groups) |
| `deletionPolicy` | `Delete` / `Orphan` | no such field | [deletionPolicy](#deletionpolicy) |
| `providerConfigRef` | `{name: default}` → cluster-scoped `ProviderConfig` | omitted, or a `kind` naming an object that exists | [providerConfigRef](#providerconfigref) |
| Secret references | `name` + `namespace` | no `namespace`: the resource's own | [Secret references](#secret-references) |
| XR connection secret | `writeConnectionSecretToRef` on the XR | the function composes a `Secret` | [Connection secrets](#connection-secrets) |
| Composition | `apiextensions.crossplane.io/v1` | unchanged — there is no v2 Composition | [Composition](#composition) |
| `compositionSelector`, `compositionRef`, … on the XR | `spec.<field>` | `spec.crossplane.<field>` | [Examples](#examples) |
| Example XRs | cluster-scoped, or a claim | the XRD's Kind, with `metadata.namespace` | [Examples](#examples) |

Rolling out to a control plane where the v1 API is installed is a separate problem:
[Installed v1 APIs](#installed-v1-apis).

## Project file

```yaml
apiVersion: meta.dev.upbound.io/v2alpha1   # was v1alpha1
kind: Project
```

The schema is otherwise the same (`v2alpha1` adds `spec.paths.operations`); `up` converts
between the two. Provider dependencies move to releases that serve the `.m.` groups
([Provider API groups](#provider-api-groups)). A function that builds a `Secret` from typed
models needs the Kubernetes API models:

```yaml
spec:
  apiDependencies:
  - k8s:
      version: v1.33.0
    type: k8s
```

Then `up dep update-cache` and `up project build` regenerate the models.

## XRD

```yaml
# v1
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xnetworks.platform.example.com
spec:
  group: platform.example.com
  names:
    kind: XNetwork
    plural: xnetworks
  claimNames:
    kind: Network
    plural: networks
  connectionSecretKeys: [vpcId]
```

```yaml
# v2
apiVersion: apiextensions.crossplane.io/v2
kind: CompositeResourceDefinition
metadata:
  name: xnetworks.platform.example.com   # unchanged: <plural>.<group>
spec:
  scope: Namespaced                      # the v2 default; write it anyway
  group: platform.example.com
  names:
    kind: XNetwork                       # kept: see "Kind and the X prefix"
    plural: xnetworks
  # claimNames and connectionSecretKeys removed
```

A v2 XRD rejects the removed fields with `Claims aren't supported in
apiextensions.crossplane.io/v2` and `XR connection secrets aren't supported in
apiextensions.crossplane.io/v2`. `defaultCompositeDeletePolicy` only governs claims; remove it
too. The schema under `versions[]` carries over, apart from the parameters in
[deletionPolicy](#deletionpolicy) and [Secret references](#secret-references). Schema quality
(`required`, `status`) is `control-plane-project-charter/references/charter/xrd-design.md`;
open-ended maps such as tags are `additionalProperties` (author-configuration-package's SKILL.md).

## Kind and the X prefix

Keep the existing Kind. The X prefix is a v1 naming convention, not a v2 requirement; a v2 XRD
may keep `XNetwork`.

Renaming the Kind is a new API, not a migration step: `spec.names` is immutable on an XRD
(`Value is immutable`), so a new Kind means a new XRD (`<plural>.<group>`), and existing objects
of the old Kind are not converted
(`control-plane-project-charter/references/charter/xrd-design.md`). Do it only as a deliberate,
recorded decision — for example when users only ever wrote claims and the claim Kind (`Network`)
is the name they know. The rename then carries into `compositeTypeRef.kind`, every example and
test, and optionally the directories
([Directory and function names](#directory-and-function-names)).

## Provider API groups

Managed resources move to the `.m.` groups (`.m.` = modern; `control-plane-project-charter` §5):

| Provider | v1 group | v2 group |
|---|---|---|
| Upbound AWS / Azure / GCP | `<service>.aws.upbound.io` | `<service>.aws.m.upbound.io` |
| crossplane-contrib (kubernetes, helm, …) | `<…>.crossplane.io` | `<…>.m.crossplane.io` |

- **The version can change.** A `.m.` group often starts again at `v1beta1`: legacy
  `ec2.aws.upbound.io` serves `v1beta1` and `v1beta2`, `ec2.aws.m.upbound.io` only `v1beta1`.
  Take the version from the generated models, never from the v1 code.
- **Only newer provider releases serve `.m.` groups** — the Upbound provider families from
  their v2 releases on. Check every dependency (`plan-v2-migration` Phase 3).
- **Each provider family moves separately**: a project using AWS and Azure changes both.
- **Spelling per language** (the charter's language file has the exact form):

| Language | v1 → v2 |
|---|---|
| KCL | `models.io.upbound.aws.ec2.v1beta1` → `models.io.upbound.awsm.ec2.v1beta1` — KCL only: the `m` joins the cloud segment (`azurem`, `gcpm` likewise) |
| Python | `models.io.upbound.aws.ec2.vpc` → `models.io.upbound.m.aws.ec2.vpc` |
| Go | `dev.upbound.io/models/io/upbound/aws/ec2/v1beta1` → `dev.upbound.io/models/io/upbound/m/aws/ec2/v1beta1` |
| go-templating, YAML | the `apiVersion` string itself |

## deletionPolicy

A namespaced managed resource has no `deletionPolicy` field. Map it:

| v1 | v2 |
|---|---|
| `deletionPolicy: Delete` (the default) | set nothing — the CRD default `managementPolicies: ["*"]` deletes |
| `deletionPolicy: Orphan` | `managementPolicies: ["Create", "Observe", "Update", "LateInitialize"]` |

Never write `["*"]` explicitly. If the v1 XRD exposed a `deletionPolicy` parameter, keep the
parameter and map it in the function as above:

```yaml
# XRD parameter: unchanged from v1
deletionPolicy:
  type: string
  enum: [Delete, Orphan]
  default: Delete
```

Or expose `managementPolicies` instead, with no `default`, and pass it through only when set.

## providerConfigRef

Namespaced managed resources default it to `{kind: ClusterProviderConfig, name: default}`.
Omit it if and only if `ClusterProviderConfig/default` exists and is the right one; the rule is
`control-plane-project-charter` §5.

| v1 code | v2 |
|---|---|
| `providerConfigRef: {name: default}` | delete it |
| no `providerConfigRef` | nothing to do |
| `providerConfigRef: {name: team-a}` | keep it as `{kind: ClusterProviderConfig, name: team-a}`, and record that the platform needs a `ClusterProviderConfig` of that name in the provider's `.m.` group — the v1 `ProviderConfig` is not one |
| a name the XR passes in | keep the parameter; add the `kind` |

Deleting a non-`default` reference silently repoints those resources at the default credentials.
`kind: ProviderConfig` selects a *namespaced* config in the resource's namespace: it is a bug
only when no `ProviderConfig` of that name exists in, or is created in, the XR's namespace. The
symptom of a missing one: `control-plane-project-charter/references/charter/v2-resources.md`.

## Secret references

Secret references on a namespaced managed resource (`passwordSecretRef`,
`writeConnectionSecretToRef`, …) have no `namespace`: the Secret must be in the resource's
namespace, which is the XR's. Remove `namespace` from them, and record that a Secret which lived
in `crossplane-system` must now exist in the XR's namespace. If the XRD exposes a secret
reference with a `namespace`, drop it from `required` and stop reading it.

Do not set `metadata.namespace` on a composed resource either: for a namespaced XR Crossplane
overwrites it with the XR's. An object embedded in `forProvider`, such as the manifest of a
provider-kubernetes `Object`, is the exception: nothing fills in its namespace, so set it
(`control-plane-project-charter` §5).

## Connection secrets

Only legacy cluster-scoped XRs write connection secrets. For a namespaced XR,
`writeConnectionSecretToRef` (XR) and `writeConnectionSecretsToNamespace` (Composition) do
nothing, and the Composition's `publishConnectionDetailsWithStoreConfigRef` is gone (v2 has no
external secret stores). To keep exposing connection details, the function composes a `Secret`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <xr-name>-connection   # no namespace: Crossplane sets the XR's
data:
  endpoint: <base64>           # from a composed resource's status.atProvider
  password: <base64>           # from a composed resource's observed connection details
```

- The values come from observed state — the composed resources' `status` and connection
  details — so this branch never runs in a plain render. Crossplane passes a composed resource's
  connection details to the function only when that resource sets `writeConnectionSecretToRef`
  (keep it, without `namespace`: Secret references, above), and a function must not fall back to
  an empty value when one is missing (`control-plane-project-charter` §5). Cover the status
  values with `observedResources` in a test, and the connection details and the reference as
  `control-plane-project-charter/references/charter/v2-resources.md` says.
- `data` is base64. How each SDK exposes observed connection details (KCL sees them already
  base64-encoded) is in the language file.
- Several composed resources can feed one Secret.
- Whatever read the v1 XR's connection secret now reads this Secret, in the XR's namespace.

## Composition

- Stays `apiextensions.crossplane.io/v1`: there is no v2 Composition.
- Remove `writeConnectionSecretsToNamespace`.
- `compositeTypeRef` changes only if the Kind was renamed.
- Crossplane v2 removed native patch-and-transform (`mode: Resources`); convert such a
  composition to a function pipeline first (`crossplane beta convert pipeline-composition`,
  Crossplane v1.20 CLI).

## Examples

```yaml
# v1
apiVersion: platform.example.com/v1alpha1
kind: XNetwork
metadata:
  name: my-network
spec:
  compositionSelector:
    matchLabels:
      provider: aws
  parameters:
    region: us-west-2
  writeConnectionSecretToRef:
    name: network-secret
    namespace: default
```

```yaml
# v2
apiVersion: platform.example.com/v1alpha1
kind: XNetwork
metadata:
  name: my-network
  namespace: default
spec:
  crossplane:
    compositionSelector:
      matchLabels:
        provider: aws
  parameters:
    region: us-west-2
```

- Add `metadata.namespace`.
- Crossplane's own fields move under `spec.crossplane`: `compositionRef`,
  `compositionSelector`, `compositionRevisionRef`, `compositionRevisionSelector`,
  `compositionUpdatePolicy`, `resourceRefs`.
- Remove `writeConnectionSecretToRef`.
- A claim example (its Kind is the v1 `claimNames.kind`) becomes an XR of the XRD's Kind.

## Tests

- **Composition tests:** the XR input changes like an example (namespace, `spec.crossplane`,
  Kind as kept). Expected managed resources use the `.m.` `apiVersion` at the version the models
  show. Do not add `providerConfigRef`, `managementPolicies` or a namespace to an expected
  resource (a namespaced MR has no `deletionPolicy`) unless the function sets it — what a render
  shows of the CRD defaults differs by language
  (`control-plane-project-charter/references/charter/v2-resources.md`). Assert a composed
  connection `Secret`'s status values with `observedResources`, and `writeConnectionSecretToRef`
  on each resource it reads connection details from (Connection secrets, above).
- **Test code** in KCL, Python or Go switches its imports the way the function does.
- **E2E tests:** manifests become namespaced XRs; `spec.crossplane.version`, if set, names a
  Crossplane v2 release; the ProviderConfig the test creates follows `author-tests`
  `e2e.md`.

## Directory and function names

Keep them: `functions/xnetwork/` and `tests/test-xnetwork-basic/` work in v2. A function's
directory name is the suffix of its published package name and of `functionRef.name`
(`<org>-<repo><dir>`, `control-plane-project-charter/references/charter/generators.md`), so
renaming one publishes a new package. Rename only together with a
deliberate Kind rename, and never add a language suffix (`-python`, `-kcl`, `-go`).

## Installed v1 APIs

This migration changes the project, not a control plane where the v1 version is installed:

- `spec.scope`, `spec.names` and `spec.group` are immutable on an XRD (`Value is immutable`),
  so the v2 XRD cannot replace an installed `LegacyCluster` XRD of the same name in place.
- Existing XRs, claims and managed resources are not converted, and Crossplane ships no
  migration tooling for them yet (crossplane/crossplane#6726).
- Crossplane's upgrade guide warns against changing a composition that live XRs use.

Record this in the plan as a rollout risk for the user to decide. Never delete an installed
XRD, XR or claim to make room for the new one: that deletes the composed cloud resources.
