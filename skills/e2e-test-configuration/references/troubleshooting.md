# E2E troubleshooting

Read when a run is stuck or has failed, or before you call an error terminal. [SKILL.md](../SKILL.md) has
the workflow; how to reach the control plane while it exists is in [local.md](local.md) or
[space.md](space.md); the report shapes are in [report-templates.md](report-templates.md).

## Transient or terminal?

1. **A threshold is when to start asking, not a verdict.**
2. **Transient needs recurrence, not just duration.** The same error three times is a resource that failed,
   recovered and failed again; one error spanning the window is a resource still converging.
3. **Match by shape, not phrase.** `<entity> <identifier> does not exist` ("database username … does not
   exist") is dependency ordering: a sibling not ready yet. A bare "does not exist" can name the object's own
   invalid field, a real rejection.
4. **Validation-rejection wording is terminal**, whatever status code it arrived in; providers wrap
   request-validation errors in 500s.

Known transient:

- `failed to get restmapping: no matches for kind` early in a run (provider CRDs not installed yet).
- `unexpected status code 429` (or 502/503) from `xpkg.upbound.io` at `Checking dependencies` or during
  control-plane creation: a registry rate limit. Retry with backoff rather than diagnosing it; a failure
  during control-plane creation can leave the control plane behind, so check for leftovers before the retry
  (the target's reference).

Target-specific ones are in the target's reference.

## Resources under test

Kinds, names and namespaces of the test's manifests, for `crossplane beta trace` and the brief below. Match
the test directory's language. Select only `spec.manifests`: `extraResources` carry the credential, and it must
not land in your output.

```bash
# Go (tests/<n>/go.mod): the program prints the test YAML; it needs the UP_* inputs set
(cd tests/<n> && go run .) | yq -o json '.items[].spec.manifests'

# KCL (tests/<n>/*.k)
kcl tests/<n>/ | yq -o json '.items[].spec.manifests'

# Python SDK layout (tests/<n>/test/__main__.py): up runs it in a container (hatch run test), but it also
# runs on the host once setup_venv.py has installed the test directory; there it sees your full environment
(cd tests/<n> && UP_AWS_CREDENTIALS=x ../../.venv/bin/python -m test) | yq -o json '.items[].spec.manifests'

# go-templating (tests/<n>/*.gotmpl): rendered in-process by up; `up test run --help` (v0.55.0) offers no
# flag that prints the generated test. Read kinds and names from the template.

# YAML (tests/<n>/*.yaml)
yq -o json '.items[].spec.manifests' tests/<n>/*.yaml
```

Then:

```bash
... | jq -r '.[] | [(.kind | ascii_downcase), .metadata.name, .metadata.namespace] | @tsv'
```

A resource whose trace shows `Creating` is not stuck: VPN gateways, NAT gateways and RDS take time.

## Stuck investigation brief

Hand this to a sub-agent when a run crosses the stuck threshold with nothing `Creating`, or follow it yourself
if your harness has no sub-agents (charter §1). Fill in the kubeconfig from the target's reference.

```text
You are troubleshooting a stuck Crossplane E2E test.

Context:
- Test: <test-name>, target: <local kind | Space <space>/<group>>
- Control plane: <project>-uptest-<test>
- Kubeconfig for it: <path>  (written fresh in this run; use --kubeconfig on every command)
- Resource: <kind>/<name> in <namespace>
- Phase when stuck: <phase>
- Last output: <last lines of the log>

Steps:

1. Stuck at "Waiting for package": check the package before any managed resource.
   kubectl get pkgrev -o wide --kubeconfig <path>
   kubectl describe configuration --kubeconfig <path>

2. Stuck at "Applying Extra Resources", or the provider cannot authenticate:
   kubectl get clusterproviderconfig,providerconfig -A -o wide --kubeconfig <path>
   (never print a Secret's data)

3. Resource status:
   kubectl get <kind> <name> -n <namespace> -o yaml --kubeconfig <path>
   kubectl get managed -o wide --kubeconfig <path>
   KUBECONFIG=<path> crossplane beta trace <kind> <name> -n <namespace> -o wide

4. Events:
   kubectl get events -n <namespace> --sort-by='.lastTimestamp' --kubeconfig <path> | tail -50

5. Provider and function logs (find their namespace first):
   kubectl get pods -A -l pkg.crossplane.io/provider --kubeconfig <path>
   kubectl logs -n <namespace> -l pkg.crossplane.io/provider --tail=200 --kubeconfig <path> | grep -iE 'error|denied|auth'
   kubectl logs -n <namespace> -l pkg.crossplane.io/function --tail=200 --kubeconfig <path> | grep -i error

6. Map the symptom to a cause with the failure-pattern table you were given.

Return only this (max 100 lines):

## Root cause
Primary issue: <1-2 sentences>
Cause: <2-3 sentences>
Category: <composition | provider | credentials | infrastructure | test definition>

## Proposed fixes
1. <issue>: file <path>; problem <what is wrong>; change <what to change>

## Key evidence
- <quoted error or condition>
```

Hand the sub-agent the table below with the brief. Its report decides what happens to the run:

- **A terminal cause** ([Transient or terminal?](#transient-or-terminal)): waiting cannot fix it, so stop the
  run and report it as terminated, with the analysis. A stopped run can skip up's teardown and leave the
  control plane with live cloud resources on it: clean up as
  `control-plane-project-charter/references/charter/targets.md` ("Delete the XRs, and wait, before the control
  plane") says, before you report.
- **Anything else**, including no cause found: keep waiting. The test's own `timeoutSeconds` ends the run, and
  up tears it down; report that outcome with the analysis.

## Failure patterns

| Symptom | Likely cause |
|---|---|
| Stuck at `Waiting for package to be ready` | package install failed or a dependency did not resolve; on a Space, often a private repository ([space.md](space.md)); on `--local`, a run under `umask 077` (`docker logs <cluster>-registry`; [local.md](local.md) Preconditions) |
| Stuck at `Applying Extra Resources` | invalid ProviderConfig, missing Namespace or Secret |
| `.spec.credentials.secret: field not declared in schema` | ProviderConfig shape: it is `secretRef`, not `secret` (author-tests' `e2e.md` reference) |
| `InvalidClientTokenId` | credential value malformed, e.g. `session_token` instead of `aws_session_token`: check the Secret's format |
| `AccessDenied` | the credential works but lacks a permission |
| `ProviderConfig not found` | the referenced config does not exist: wrong `kind` (a namespaced `ProviderConfig` nobody created), wrong name, or wrong API group — `control-plane-project-charter/references/charter/v2-resources.md` |
| `SyntaxError: Expected TOKRbracket …` or `field not found in the input object` | a `defaultConditions` entry is not a condition type: a broken test, not RED |
| Assert fails on the `Ready` entry (the error line names `type == 'Ready'`) | the resource never became Ready: often a missing composed resource or a selector that matches nothing; rule out credentials first. The `status: {}` in chainsaw's diff is how chainsaw prints the projection, not the resource's status: it appears on a Ready XR too. Read the conditions during the run ([local.md](local.md)) |
| Function errors | composition code; reproduce with the composition tests |
| Resources `Creating`, no errors | slow cloud API (normal), or an auth problem that has not surfaced yet |
