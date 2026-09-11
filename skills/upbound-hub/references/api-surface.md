# API surface

Versions differ by group, and by deployment. The tables below are what to expect,
not a guarantee: a Hub serving `authentication.hub.upbound.io` at v1alpha1 and
v1beta1 but not v1 exists, so `hub-list` asks `/apis` and drops a pinned version
the server does not serve. Check any deployment you are on:

```bash
scripts/hub-curl /apis | jq '.groups[] | {name, versions: [.versions[].version]}'
scripts/hub-curl "/apis/$GROUP/$VERSION" | jq '.resources[] | {name, namespaced, verbs}'
```

### Hub 1.0.x

| Group | Versions served |
|---|---|
| `hub.upbound.io` | v1alpha1, v1alpha2, **v1beta1** |
| `ingest.hub.upbound.io` | v1alpha1, v1beta1 |
| `authentication.hub.upbound.io` | v1alpha1, v1beta1, and on some deployments v1 |
| `authorization.hub.upbound.io` | v1alpha1, v1beta1 |
| `catalog.hub.upbound.io` | v1alpha1 |

### Hub 1.1.0

Verified against a live 1.1.0 deployment. `/apis` returned exactly six groups:

| Group | Versions served | Serves |
|---|---|---|
| `hub.upbound.io` | **v1beta1** | `realms` only |
| `inventory.hub.upbound.io` | **v1beta1** | `resources`, `resourcestats`, `lenses`, `typedefinitions`, `crossplanepackages`, `resourcerelationships`, `resourcerelationshiptrees` |
| `fleet.hub.upbound.io` | **v1beta1** | `controlplanes`, `spaces`, `controlplaneregistrations`, `spaceregistrations` |
| `iam.hub.upbound.io` | **v1beta1** | `identityproviders`, `users`, `groups`, `organizationrolebindings`, `realmrolebindings`, `selfsubjectaccessreviews` |
| `ingest.hub.upbound.io` | v1alpha1, **v1beta1** | `resourceevents` |
| `authentication.k8s.io` | v1 | Kubernetes core |

`authentication.hub.upbound.io` and `authorization.hub.upbound.io` are **gone**,
merged into `iam.hub.upbound.io`. A bootstrap file still using
`authorization.hub.upbound.io/v1beta1` will fail with `no kind "RealmRoleBinding"
is registered for version ...`.

`catalog.hub.upbound.io`, `registry.hub.upbound.io` and `agent.hub.upbound.io`
did not appear on the deployment tested, which had the `Catalog`, `Registry` and
`AgentSessions` feature gates **off**. Absence here is not evidence of removal.
Check `/apis` on a deployment with those gates enabled before concluding either way.

**Do not pin a group.** `scripts/hub-list` and `scripts/hub-stats` resolve group
and version from `/apis`. Within a group, target v1beta1; the v1alpha1 `Resource`
and `ResourceStats` types are deprecated.

## Core resources

On 1.0.x these are all under `hub.upbound.io/v1beta1`. On 1.1.0 they are split
across `inventory.`, `fleet.` and `hub.` as in the table above; the shapes and
verbs are unchanged.

| Resource | Scope | Verbs | Notes |
|---|---|---|---|
| `controlplanes` | namespaced | CRUD | The namespace **is the realm name**. `status.phase`. Subresources: `registrationtoken` (create), `jwks` (update, connector-only). |
| `controlplaneregistrations` | cluster | create | Register a control plane. |
| `spaces` | cluster | CRUD | `status.phase`. Subresource `registrationtoken` (create). |
| `spaceregistrations` | cluster | create | |
| `realms` | cluster | create, get, list, delete | **No update.** Realms are also namespaces — see writing.md before deleting one. |
| `lenses` | cluster | CRUD | Saved filter and sort presets. |
| `crossplanepackages` | cluster | get, list | Hub's catalog. No `status`. Behind a feature gate. |
| `typedefinitions` | cluster | get, list | Every CRD, XRD and MRD across the fleet. Behind a feature gate. |
| `resources` | cluster | get, list | The inventory. CEL `filter` — see [querying.md](querying.md). |
| `resourcestats` | cluster | create | Aggregation. The only correct way to count. |
| `resourcerelationships` | cluster | get | `?relationType=composes\|composedBy\|references\|referencedBy` |
| `resourcerelationshiptrees` | cluster | get | `depth` (0 means 3, max 10), `direction` (`up`, `down`, `both`) |

### There is no `patch` and no `watch`

The handler serves `get`, `list`, `create`, `update`, `delete` and 405s
everything else. Three consequences:

- **`kubectl apply` works once.** On an object that already exists it sends a
  merge PATCH and gets a 405. Use `kubectl replace`. Same for `kubectl edit`,
  `label`, and `annotate`.
- **`kubectl get -w` 405s.** "Wait until ready" has to be a polling loop.
- **kubectl paginates with `limit`/`continue`**, which Hub does not implement,
  so `hub-kubectl get` on a collection silently returns one page. Read with
  `hub-list`.

### Object shapes

`resources` items carry `source.{apiVersion,kind,name,namespace}`,
`location.controlPlaneRef.{name,realm}`, `status.conditions[]` (only when the
source has them), and `hub.{lastSyncTime,syncLagSeconds}`.

`typedefinitions` items carry `definition.{group,kind,scope,categories}`,
`definedBy.{CustomResourceDefinition,CompositeResourceDefinition,ManagedResourceDefinition}`
as counts, and `summary.{controlPlaneCount,resourceCount,versionCount}`.

## Other groups

| Group | Resources |
|---|---|
| `authentication.hub.upbound.io` (1.0.x) / `iam.hub.upbound.io` (1.1.0) | `identityproviders`, `users`, `groups` — **version varies**; `users` and `groups` require an `identityProvider` query parameter, and `users` a `group` as well |
| `authorization.hub.upbound.io/v1beta1` (1.0.x) / `iam.hub.upbound.io/v1beta1` (1.1.0) | `organizationrolebindings` (cluster), `realmrolebindings` (namespaced), **`selfsubjectaccessreviews`** (create) |
| `catalog.hub.upbound.io/v1alpha1` | `images` (subresources `usage`, `curated`, `openapi`), `imagesearches` (create-only, cannot be listed) |
| `registry.hub.upbound.io` | `repositories`, `connections` (namespaced) |
| `agent.hub.upbound.io` | `sessions`, subresource `messages` |
| `ingest.hub.upbound.io` | `resourceevents` — the connector's write path, not yours |
| core `/api/v1` | `namespaces` — **realms are exposed as namespaces** |

Identity providers, role bindings, and the image catalog are all Hub groups.

## Subresource paths

Spell these out; they are easy to get wrong:

```
/apis/{inventory.hub.upbound.io on 1.1.0}/v1beta1/resources/{name}/events
/apis/{inventory.hub.upbound.io on 1.1.0}/v1beta1/typedefinitions/{name}/distribution
/apis/{inventory.hub.upbound.io on 1.1.0}/v1beta1/crossplanepackages/{name}/distribution
/apis/{fleet.hub.upbound.io on 1.1.0}/v1beta1/namespaces/{realm}/controlplanes/{name}/registrationtoken
/apis/catalog.hub.upbound.io/v1alpha1/images/{name}/usage
```

## Reading an error

- **401** — the session expired. Re-run `scripts/hub-setup`.
- **403** — authorization. Ask `selfsubjectaccessreviews` what the caller may do.
- **404 on a whole resource** — the feature gate for it is off in this
  deployment, not "the API does not have it". `typedefinitions`,
  `crossplanepackages`, catalog, registry, and agent sessions are each gated.
- **405** — a verb that does not exist here, almost always `patch` or `watch`.
