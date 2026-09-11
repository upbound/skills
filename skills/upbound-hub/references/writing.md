# Writing

Use `scripts/hub-kubectl`, which points kubectl at Hub through a temporary
kubeconfig.

```bash
scripts/hub-kubectl get controlplanes -A
scripts/hub-kubectl replace -f controlplane.yaml -n <realm>
```

## Check first, do not probe by writing

Hub serves `selfsubjectaccessreviews`, so ask before acting. Do **not** discover
permissions by attempting the operation — an earlier version of this skill said
to, and for `delete` that is destructive.

It is in `authorization.hub.upbound.io` on Hub 1.0.x and `iam.hub.upbound.io` on
1.1.0, and in neither case `authorization.k8s.io`, so
`kubectl auth can-i` will not work. The spec field is `hubResourceRequest`, not
upstream's `resourceAttributes`, and `group`, `version`, `resource` and `verb`
are all required. Omitting any of them is a 422, which is not a denial — do not
read a validation error as "not permitted".

The group below is `authorization.hub.upbound.io` on Hub 1.0.x and
`iam.hub.upbound.io` on 1.1.0; substitute it in both the `apiVersion` and the
URL. The `group` inside `hubResourceRequest` names the resource being checked,
not the review's own group, so `realms` stays `hub.upbound.io` on both:

```bash
printf '%s' '{
  "apiVersion": "authorization.hub.upbound.io/v1beta1",
  "kind": "SelfSubjectAccessReview",
  "spec": {"hubResourceRequest": {
    "group": "hub.upbound.io", "version": "v1beta1", "resource": "realms",
    "verb": "delete", "name": "us-west"
  }}
}' | scripts/hub-curl /apis/authorization.hub.upbound.io/v1beta1/selfsubjectaccessreviews \
      -X POST -H 'Content-Type: application/json' --data-binary @- \
  | jq '.status'
```

`realm` decides the scope, and leaving it out is not neutral: absent means
cluster-scoped resources only, `""` means every realm of a realm-scoped
resource, and a name means that realm. Asking about `controlplanes` without a
realm is therefore not the question you meant. `name` empty means any name, and
`subresource` scopes to a subresource.

The answer is `.status.decision`, not upstream's `.status.allowed`, and there
are three outcomes:

| `decision` | What it means |
|---|---|
| `Allow` | Permitted. |
| `Deny` | Not permitted. |
| `Filtered` | Permitted for **some rows only**. `.status.filter` holds the predicate. |

`Filtered` is the one that causes wrong answers. It arrives looking like
success, and `.status.filter` is what narrows it — for example
`{"stringVarIn": {"variable": "realm", "values": ["default"]}}` allows the verb
only in the `default` realm. Treat it as a no for anything outside the filter,
and say which realms it covers rather than reporting plain access. `filter` is
populated only for `Filtered`.

`.status.error` can be set alongside either `Allow` or `Deny`, and
`.status.reason` is a human-readable explanation.

`SelfSubjectRulesReview` genuinely does not exist — you cannot enumerate every
permission, only ask about a specific one.

## Before you write

- **`apply` works once.** There is no `patch` verb, so on an existing object
  kubectl's merge PATCH gets a 405. Use `replace`.
- **The namespace must be in the manifest.** Hub does not default it from the
  URL, so `-n foo` and `metadata.namespace` must both be set and agree.
- **A ControlPlane's namespace is its realm name.**
- Ask the user for the spec rather than inventing one, especially for `lenses`,
  `identityproviders`, and role bindings.

## Minimum viable manifests

```yaml
apiVersion: hub.upbound.io/v1beta1     # fleet.hub.upbound.io/v1beta1 on Hub 1.1.0
kind: ControlPlane
metadata:
  name: <name>
  namespace: <realm>      # required, and it is the realm name
spec: {}
```

```yaml
apiVersion: hub.upbound.io/v1beta1     # fleet.hub.upbound.io/v1beta1 on Hub 1.1.0
kind: Space
metadata:
  name: <name>
spec: {}
```

```yaml
apiVersion: hub.upbound.io/v1beta1     # unchanged on Hub 1.1.0
kind: Realm
metadata:
  name: <name>
spec: {}
```

## Deleting a realm

Realms have no `update` verb. That does not make "delete and recreate" an
editing technique — it means the fields are immutable by design, and deleting
one has consequences the verb list does not show:

- **A realm is a namespace.** Deleting it removes the container every
  ControlPlane in that realm lives in.
- **Creating a realm grants realm-admin to whoever created it.** Recreating
  therefore re-authorizes the caller and does *not* restore anyone else's role
  bindings. You will silently change who administers it.
- The default realm is protected and returns 403.

So: list the dependent control planes first, tell the user exactly what will be
removed, and get explicit agreement. Do not present it as a way to rename a realm.

```bash
scripts/hub-kubectl get controlplanes -n <realm>
```

## Registration tokens

A subresource POST. The body must carry full TypeMeta matching the parent kind
even though it is otherwise ignored, and `-f /dev/null` therefore fails:

```bash
# apiVersion is fleet.hub.upbound.io/v1beta1 on Hub 1.1.0
printf '%s' '{"apiVersion":"hub.upbound.io/v1beta1","kind":"ControlPlane",
  "metadata":{"name":"<name>","namespace":"<realm>"}}' \
| scripts/hub-kubectl create --raw \
    "/apis/fleet.hub.upbound.io/v1beta1/namespaces/<realm>/controlplanes/<name>/registrationtoken" \
    -f - \
| jq -r '.status.registrationToken'
```

The response is a full ControlPlane with the credential at
`.status.registrationToken`. `create --raw` prints the whole object to stdout, so
extract the field or redirect to a `umask 077` file. **Do not echo it into a
transcript, a log, or a file the user did not ask for.**

## Do not write here

- **`ingest.hub.upbound.io/resourceevents`** — the connector's ingestion path.
  Writing to it by hand corrupts the fleet view.
- **`controlplanes/{name}/jwks`** — the connector updates this. Writing it
  replaces a control plane's connector JWKS and triggers an authenticator
  reload, breaking that control plane's authentication to Hub. It is
  update-only, so there is no safe read-modify-write.
