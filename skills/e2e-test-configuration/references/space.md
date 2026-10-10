# Running E2E on an Upbound Space (Upbound Cloud)

Read before running `up test run --e2e` against a Space. [SKILL.md](../SKILL.md) has what both targets share:
preconditions, the run idiom, stuck detection and the report. Facts come from the up v0.55.0 source and earlier
runs of this skill, and may change between versions.

## Preconditions

Run these after SKILL.md Phase 2's build, composition and credential checks, stopping at the first failure.

**1. The context names a group.** Derive it; never hardcode one:

```bash
up ctx . --short                       # <org>/<space>/<group>[/<control-plane>]
GROUP=$(up ctx . --short | cut -d/ -f3)
[ -n "$GROUP" ] || echo "no group in context; select one with 'up ctx <org>/<space>/<group>'"
```

No group in the context, or a group that does not exist: report it, and never create one (SKILL.md Never). How
`up` picks the group and the non-interactive `up ctx` forms:
`control-plane-project-charter/references/charter/targets.md`.

**2. The repository the package is pushed to is pullable.** A private one wedges the run on
`Waiting for package to be ready` and ends it with `context deadline exceeded` (why:
`control-plane-project-charter/references/charter/targets.md`). A one-second check predicts it:

```bash
REPO=$(yq -r '.spec.repository // .metadata.name' upbound.yaml | sed 's|.*/||')
up repository get "$REPO" --format=json 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d; print("public =", d.get("public"))' \
  || echo "repository does not exist yet"
```

`public = True` → go on. Anything else needs a decision that is not yours: `--public` only makes a repository
it *creates* public, so it fixes "does not exist yet" and changes nothing for an existing private one
(`control-plane-project-charter/references/charter/targets.md`).

- If the user already chose `--public` (earlier in the conversation, or relayed in the brief by an
  orchestrating agent as the user's explicit choice), use it; don't ask again. An orchestrator never decides
  it itself.
- Otherwise, before burning a run, name the options: publish publicly, change the existing repository's
  visibility (the user's call, outside this skill), push to a repository the control plane can already pull
  from (`--repository`), or have the caller choose the local target instead. Interactive, ask; unattended,
  stop and report. **Never add `--public` because a run hung: it permanently publishes the user's package.**

**3. Credentials.** `source: Upbound` web identity works here, and only here. Each test gets its own control
plane named `<project>-uptest-<test>`, so a trust policy needs a wildcard subject (inference). A static Secret
works too. Shapes: author-tests' `e2e.md` reference.

## Target flags

Write the kubeconfig fresh in this run and check it parses, as
`control-plane-project-charter/references/charter/targets.md` ("`--kubeconfig` is an input") shows: a stale file
sends the run to local kind. Shell variables do not survive to your next command, so reuse the group and the
file path as values. Pass `--control-plane-group` explicitly even when the context names the group. The target
flags for SKILL.md Phase 4's run idiom are then:

```bash
up test run "tests/e2etest-<n>" --e2e --control-plane-group="<group>" --kubeconfig "<kubeconfig>"
# add --public ONLY if the user chose it
```

## What the run does

1. Creates a control plane `<project>-uptest-<test name>` in the group. The first progress line is `Creating
   development control plane in Spaces`.
2. Crossplane version: `spec.crossplane.version` or `--control-plane-version` if set; otherwise the latest
   version matching the project's constraint (`^v2.0.0-up.0` for a v2 project). `spec.crossplane.autoUpgrade.channel`
   applies here.
3. Pushes the built package to the repository, applies `initResources`, installs the Configuration and waits
   for it, then applies `extraResources` without waiting.
4. Applies the manifests and asserts `defaultConditions` within `timeoutSeconds`.
5. Tears down after every test, pass or fail, unless `spec.skipDelete: true` or `--skip-control-plane-cleanup`.

**Timings:** 30–40 minutes per test was normal in earlier runs of this skill on a Space; not re-measured with
up v0.55.0.

**Known transient:** `Creating: Waiting for control plane API: cannot provision contr...` is a progress
message truncated mid-word (the `up ctp list` MESSAGE column), not a failure; all conditions may still settle
`True`.

## Stuck on a Space

Check the package installed before any managed resource. If the run never got past
`Waiting for package to be ready`, no XR exists and there is nothing to trace: read the `Configuration` as
`control-plane-project-charter/references/charter/targets.md` ("A run stuck on
`Waiting for package to be ready`") says. A `401 Unauthorized` there is precondition 2's private repository:
retrying does not help; hand back that precondition's options.

For the brief in [troubleshooting.md](troubleshooting.md), get the test control plane's kubeconfig while it
exists:

```bash
CPCFG=$(mktemp -t kubeconfig-cp.XXXXXX)
up ctx ./<control-plane-name> -f - > "$CPCFG"   # from the group context
echo "kubeconfig: $CPCFG"   # reuse the path as a value: the variable is gone by your next command
```

Once you are done with it, `rm -f <kubeconfig>`, and the run's own `--kubeconfig` file once the run has
exited (charter §9: delete what this run created).

## Evidence and cleanup

- **The log's `Cleanup summary` line**, quoted. A remaining count above 0 is orphaned cloud resources
  (what the counts mean: `control-plane-project-charter/references/charter/targets.md`, Teardown and
  leftovers).
- **Resource and provider reads taken during the run**, through the control plane's kubeconfig above; the
  control plane is deleted afterwards.
- **No test control plane left behind:** `up controlplane list` shows no `<project>-uptest-<test>` once the run
  has exited, unless the test skips deletion.
- **Leftovers in the cloud**, checked in the provider's API by the names or tags the test used.
