# Activating managed resources: ManagedResourceActivationPolicy (MRAP)

What an MRAP manifest looks like, where it must sit, what `up project build` does and does not
check, how to see its effect, and what `up dep add --api` writes and which tag it takes. The
skill's MRAP line states the rule.

---

`kind: ManagedResourceActivationPolicy`, `apiVersion: apiextensions.crossplane.io/v1alpha1`,
with `spec.activate:` listing MRD names (`vpcs.ec2.aws.m.upbound.io`). Its CRD is cluster-scoped
(no `metadata.namespace`), and `spec.activate` is required with at least one entry; an entry may be
a wildcard prefix (`*.aws.m.upbound.io`), not a regular expression. Observed with up v0.55.0:

- **The manifest must sit under `apis/`** (any subdirectory, e.g. beside the XRD). Anywhere
  else (`policies/`, `examples/`) it is silently left out of the package.
- **`up project build` barely validates it.** A field typo ships an MRAP that activates
  nothing; a wrong `kind` or `apiVersion` is silently dropped; only a wrong value type fails.
  `activate` entries are not checked against any CRD. Whether it ships is in the package's
  `package.yaml` ([SKILL.md](../SKILL.md), Phase 9); whether it works, verify on a control plane.
- **The default policy hides its effect.** UXP's default MRAP activates `*`. To see yours, start
  the control plane with the Crossplane Helm value `provider.defaultActivations: []` (e.g.
  `up project run --local --helm-values <file>`; charter §9 decides whether you may) and check
  that exactly the MRDs you listed are Active. So an E2E run, or any control plane started with
  the default, proves the MRAP installs, not that it activates what you listed.
- **`up dep add --api crossplane:<tag>` writes `spec.apiDependencies`** (`- type: crossplane`
  with `crossplane: {version: <tag>}`), a list separate from `dependsOn`. It adds the MRAP models
  for Go/Python/KCL; the build does not need it, and nothing in `apiDependencies` ships in the
  package. `upbound/crossplane` and `upbound/controller-manager` are container images, not
  packages: a `dependsOn` entry for either fails `up project build` with `failed to extract
  package layer: blob : not found` (up v0.55.0). The tag must be a UXP version in both
  `upbound/crossplane` and `upbound/controller-manager`: `v2.1.4-up.1` worked; `v2.1.0`,
  `v2.1.3` and `v2.1.3-up.1` returned 404 (`v2.1.3-up.1` exists in `upbound/crossplane` only).
  Look the tag up; don't guess. A bare `tags/list` request is refused (401), but the registry hands out an anonymous
  pull token (checked 2026-10); a configured Upbound Marketplace MCP (the skill's Phase 4) lists
  versions too:

  ```bash
  for r in crossplane controller-manager; do
    t=$(curl -s "https://xpkg.upbound.io/service/token?service=xpkg.upbound.io&scope=repository:upbound/$r:pull" | jq -r .token)
    curl -s -H "Authorization: Bearer $t" "https://xpkg.upbound.io/v2/upbound/$r/tags/list" \
      | jq -r '.tags[]' | grep -E '^v2\.[0-9]+\.[0-9]+-up\.[0-9]+$' | sort > "/tmp/uxp-$r.tags"
  done
  comm -12 /tmp/uxp-crossplane.tags /tmp/uxp-controller-manager.tags   # tags in both
  ```
