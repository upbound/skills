# Querying

## Count with resourcestats, never by paging

`metadata.total.count` **saturates at 1000**. Past that the server returns
`{count: 1000, relation: "gt"}`, which may mean 1,001 or 200,000 — it carries no
magnitude. So a paged count is a lower bound, not an answer.

`resourcestats` returns a real aggregate. Use it for every "how many" question.

```bash
scripts/hub-stats                            # fleet totals
scripts/hub-stats kind                       # by kind
scripts/hub-stats controlPlane kind          # by control plane, then kind
scripts/hub-stats kind -- ready=False        # only what is explicitly not Ready
```

The raw request. **`apiVersion` and `kind` are required** — the handler decodes
with no group-version defaults and checks for an exact match, so a body of just
`{"query": …}` is a 400:

```json
POST /apis/hub.upbound.io/v1beta1/resourcestats
{
  "apiVersion": "hub.upbound.io/v1beta1",
  "kind": "ResourceStats",
  "query": {
    "filters": { "ready": "False", "controlPlanes": ["prod-1", "prod-2"] },
    "groupBy": ["kind", "controlPlane"]
  }
}
```

`groupBy` accepts `kind`, `group`, `controlPlane`, `realm`, `space`, `ready`,
`synced`, `healthy`, `crossplaneType`.

Stats filters are **their own set**, and are not the `/resources` filter fields:

| Filter | Shape |
|---|---|
| `kinds`, `groups`, `controlPlanes`, `realms`, `spaces` | arrays |
| `ready`, `synced`, `healthy` | a single `"True"` / `"False"` / `"Unknown"` |

Anything else is dropped without an error, so a query with a misspelled filter
returns the whole fleet looking like a filtered answer. `hub-stats` rejects
unknown keys rather than passing them through.

The response is under **`results`**:

```
.results.summary.totalCount        .results.summary.readyTrue / readyFalse / readyUnknown
.results.groups[].dimensions       .results.groups[].totalCount
```

## Filtering `/resources` with CEL

v1beta1 takes a single `filter` parameter holding a CEL expression, not one
parameter per field.

```bash
scripts/hub-list resources 100 'filter=controlPlane == "prod-1"'
scripts/hub-list resources 100 'filter=conditions.ready.status == "False" && realm == "us-west"'
scripts/hub-list resources 100 'filter=kind in ["Bucket", "Instance"]'
scripts/hub-list resources 100 'filter=createdAt > now() - duration("24h")'
scripts/hub-list resources 100 'filter=name.startsWith("prod-")'
```

Addressable fields:

| Field | Type |
|---|---|
| `kind`, `group`, `apiVersion`, `name`, `namespace` | string |
| `controlPlane`, `space`, `realm`, `crossplaneType` | string |
| `labels`, `annotations` | map |
| `conditions.ready.status`, `conditions.ready.message` | string |
| `conditions.synced.status`, `conditions.synced.message` | string |
| `conditions.healthy.status`, `conditions.healthy.message` | string |
| `createdAt`, `updatedAt`, `deletedAt` | timestamp |

Comparisons, `&&`/`||`/`!`, `in`, `startsWith`, `matches`, and the CEL standard
library are available, plus `now()`, `duration()` and `timestamp()`.

`view=full` includes the raw source object; `summary` is the default.

The condition *messages* are filterable, which is how you find out why something
is broken rather than only that it is.

## Pagination

`?page=N&pageSize=S`, one-indexed. Not Kubernetes `limit`/`continue` — there is
no continue token, so **`hub-kubectl get` on a large collection silently reports
one page as the whole list**. Use `hub-list` or `hub-curl` for reads.

`pageSize` is capped at 100.

There is no page ceiling. `hub-list` pages until a short page, and exits **4**
if it hits its own safety stop, so a truncated answer is distinguishable from a
complete one — a warning on stderr is invisible to `$(...)`.

## What health actually means

A `Resource` carries `status.conditions` only when its source object has
Crossplane-style conditions. Most records carry none.

Three states, not two:

- **Unhealthy** — `Ready`, `Synced`, or `Healthy` is explicitly `"False"`.
- **Healthy** — `Ready` is `"True"`.
- **Unknown** — the condition is `Unknown`, or absent. This is *not* unhealthy.
  `Ready=Unknown` is the normal state for the whole window while a managed
  resource is being created.

`readyUnknown` in the stats summary merges "reported Unknown" with "never
reported", so the only denominator the API can actually produce is
`readyTrue + readyFalse`. Report against that, and give the unknown count
separately. `hub-health` computes all three.

"12 unhealthy out of 312 assessable, with 3,888 not reporting" is an answer.
"12 unhealthy out of 4,200" is not, and "99.7% healthy" is wrong.

Three things that will skew a count if you ignore them:

- **`Synced=False` with reason `ReconcilePaused` is not broken.** Someone set
  `crossplane.io/paused: "true"`. Conditions carry `reason`; read it.
- **Composition fans out.** One broken bucket appears as an unhealthy managed
  resource *and* an unhealthy composite. Group by `crossplaneType` before
  reporting an incident count.
- **Non-Crossplane `Ready` is not health.** A `Succeeded` Pod carries
  `Ready=False` forever, so completed Job pods read as unhealthy.

## What Hub does not tell you

- **Realm and package health.** Neither has a status surface. Say so.
- **Freshness, unless you check.** Hub is an aggregator and its view is
  eventually consistent. A resource created or deleted seconds ago may not be
  reflected. `hub.lastSyncTime` and `hub.syncLagSeconds` are on every record;
  read them before making a freshness claim. Non-zero lag is normal.
