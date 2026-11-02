# The project's ProviderConfig (Phase 8)

The skill's Phase 8 states the rule.

---

A `--scratch` project has no `examples/providerconfig.yaml`; only the *language templates* ship
one. So a scratch project builds, its tests pass, it installs on a control plane — and every
managed resource it composes sits unauthenticated, because Crossplane v2 defaults an omitted
`providerConfigRef` to `{kind: ClusterProviderConfig, name: default}` and nothing in the project
creates that object. Nothing in the workflow prompts for it, and no check verifies that the
ProviderConfig a composition implicitly depends on exists. What a missing or wrong
ProviderConfig looks like on the cluster:
`control-plane-project-charter/references/charter/v2-resources.md`.

Create it in Phase 8, matching the provider family you added in Phase 4. The default is a
`ClusterProviderConfig` named `default`, below. When the project's spec or API names another
config — a namespaced `ProviderConfig` in the XR's namespace, a non-`default` name — create
that one instead, so this example and the compositions' `providerConfigRef` name the same
object (charter §5: defaults the project may override).

```yaml
# examples/providerconfig.yaml
apiVersion: aws.m.upbound.io/v1beta1     # family group, not kms.aws.m.upbound.io
kind: ClusterProviderConfig
metadata:
  name: default                          # "default", to match the v2 default ref
spec:
  credentials:
    source: Secret                       # or IRSA / WebIdentity / PodIdentity / Upbound
    secretRef:
      namespace: crossplane-system       # required, by the namespaced providerconfigs.aws.m.upbound.io CRD too
      name: aws-creds
      key: creds
```

Two things to confirm rather than guess:

- **The apiVersion is the family group** (`aws.m.upbound.io/v1beta1`), not a service group —
  a different group shape from every other resource in the family. Confirm it from the
  generated tree, where the path is the reversed group: Go
  `.up/go/models/io/upbound/m/aws/v1beta1/clusterproviderconfig.go`; Python
  `python3 <author-composition>/scripts/probe_project.py --project <root> ClusterProviderConfig`
  → `models.io.upbound.m.aws.clusterproviderconfig` = `aws.m.upbound.io` (a `grep` for
  `Literal` in that module shows the credential `source` values, not the apiVersion).
- **`ClusterProviderConfig` (cluster-scoped) vs `ProviderConfig` (namespaced)** — use the
  cluster-scoped one named `default` unless the project's spec or API calls for per-namespace
  credentials. An E2E test creates its own (author-tests' `e2e.md` reference).

Also add the credential secret to the README's prerequisites; it is not part of the package:

```bash
kubectl -n crossplane-system create secret generic aws-creds \
  --from-file=creds="${AWS_SHARED_CREDENTIALS_FILE:-$HOME/.aws/credentials}"
kubectl apply -f examples/providerconfig.yaml
```
