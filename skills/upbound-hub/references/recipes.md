# Recipes

## "How many resources are unhealthy across the fleet?"

```bash
scripts/hub-health | jq '.resources'
```

Answer with the three numbers of SKILL.md "Reporting health against the wrong denominator",
never one percentage of the total (why: [querying.md](querying.md#what-health-actually-means)).

By kind:

```bash
scripts/hub-stats kind -- ready=False
```

Group by `crossplaneType` too before calling it an incident count. One broken
bucket surfaces as both a managed resource and a composite:

```bash
scripts/hub-stats crossplaneType kind -- ready=False
```

## "What is in the fleet?"

```bash
for r in controlplanes spaces realms; do
  printf '%-20s %s\n' "$r" "$(scripts/hub-list "$r" 100 | jq length)"
done
scripts/hub-stats | jq '.results.summary.totalCount'
```

Use `hub-stats` for the resource total. A paged count saturates at 1000.

## "Which control planes are unhealthy?"

```bash
scripts/hub-list controlplanes 100 | jq -r '
  group_by(.status.phase // "Unknown")[]
  | "\(.[0].status.phase // "Unknown"): \(length)"'

scripts/hub-stats controlPlane -- ready=False
```

Then drill in:

```bash
scripts/hub-resources-by-cp prod-1 --unhealthy
```

## "Why is this thing broken?"

The condition messages are filterable, so you can find the failure rather than
just the count:

```bash
scripts/hub-list resources 100 \
  'filter=conditions.ready.status == "False" && controlPlane == "prod-1"' \
| jq -r '.[] | "\(.source.kind)/\(.source.name)\t\(
    [.status.conditions[]? | select(.status == "False")
     | "\(.type)=\(.reason): \(.message)"] | join("; "))"'
```

Filter out paused resources, which are not broken, by reason: a paused managed resource's
condition carries no message.

```bash
scripts/hub-list resources 100 'filter=conditions.synced.status == "False"' \
| jq '[.[] | select(any(.status.conditions[]?;
    .type == "Synced" and .reason == "ReconcilePaused") | not)]'
```

## "What changed recently?"

```bash
scripts/hub-list resources 100 'filter=createdAt > now() - duration("24h")'
scripts/hub-list resources 100 \
  'filter=conditions.ready.status == "False" && updatedAt > now() - duration("1h")'
```

## "What types do we have for AWS?"

```bash
scripts/hub-types aws.upbound.io
```

`summary.resourceCount > 0` means the type is in use somewhere.

## "Where did this resource come from?"

```bash
# hub.upbound.io on 1.0.x; inventory.hub.upbound.io on 1.1.0. Confirm with:
#   scripts/hub-curl /apis | jq -r '.groups[].name'
GV=inventory.hub.upbound.io/v1beta1
scripts/hub-curl "/apis/$GV/resourcerelationshiptrees/<name>?direction=up&depth=5"
scripts/hub-curl "/apis/$GV/resources/<name>/events"
```

`direction=up` walks toward the composite that owns it, `down` toward what it
composes. Depth 0 means the default of 3; the maximum is 10.

## "Did my change land?"

There is no `watch` verb, so this is a polling question — and Hub is eventually
consistent, so an immediate absence means nothing:

```bash
for i in $(seq 1 12); do
  scripts/hub-list resources 100 'filter=name == "<name>"' | jq -e 'length > 0' >/dev/null && break
  sleep 5
done
scripts/hub-list resources 100 'filter=name == "<name>"' | jq '.[0].hub'
```

Check `hub.lastSyncTime` before telling the user something does not exist.

## When the answer is "Hub does not know"

Say it. Hub exposes no health for realms or packages, no way to enumerate the
caller's permissions, and a view that lags its sources. An honest "Hub does not
expose that" beats a number assembled from something adjacent.
