# Running the project on a dev control plane

`up project run`, step by step: the Space pre-flight, the choice you hand back when a Space
cannot pull, applying credentials and an example XR, confirming the run reconciled, and what to
do when a run hangs on `Waiting for package to be ready`. The skill's Phase 5 holds the
never-rules. Where a run lands, the non-interactive `up ctx` forms, what `--public` does, and why
a private repository wedges the run are in
`control-plane-project-charter/references/charter/targets.md`: read it with this.

---

## The steps

**1. Find where the run will land.** The current context decides, not a flag:

```bash
up ctx . --short                                  # never bare `up ctx`: it needs a TTY
up ctp list >/dev/null 2>&1 && echo "Space reachable"
```

Read the result as `control-plane-project-charter/references/charter/targets.md` describes; do
not guess from the first segment.

**2. Not on a Space?** Local KIND is already the default:

```bash
up project run --timeout=20m     # the --timeout default is 5m, short for a first run
```

**3. On a Space? Pre-flight before you spend ten minutes:**

```bash
up repository get <repository>              # from upbound.yaml spec.repository; PUBLIC=false and no pull secret => it will wedge
kubectl get imageconfigs.pkg.crossplane.io
kubectl -n crossplane-system get secrets | grep -i pull
```

If the control plane can pull, run it on the Space: that is the environment they chose.

**4. If the pre-flight says it will wedge, hand the decision back.** Do not fall back to
`--local` and do not pick an option: they connected to that Space on purpose. Interactive, put
the choice to the user; unattended, report these three options and their consequences to your
caller and stop.

| Option | Command | What it costs them |
|---|---|---|
| **A. Cloud control plane, with pull access** | `up project run --timeout=20m`, once the control plane can pull | Nothing, if they can point you at a pull secret or `ImageConfig`: ask where it is rather than assuming. The only option that tests what they connected to |
| **B. Publish the repository** | `up project run --public --timeout=20m` | **Permanently publishes their package**, and does not change a repository that already exists (`control-plane-project-charter/references/charter/targets.md`). A disclosure decision, never made on their behalf |
| **C. Local KIND control plane** | `up project run --local --timeout=20m` | Nothing is pushed, so the pull failure cannot occur, and it still creates real cloud resources through their provider credentials. But it is not the Space they pointed you at, and Space-specific behaviour goes uncovered |

**5. Run it streaming.** Let the output stream, or `tee` it to a file.

**6. If it wedges anyway**, follow the next section. Another blind attempt costs another ~10
minutes and usually fails the same way.

**7. Give it something to reconcile.** The run builds, pushes and installs the Configuration,
then stops: no credentials, no ProviderConfig, no XR. Once it has exited 0, apply all three to
the control plane it created (the run made it the current context):

```bash
kubectl get configuration.pkg.crossplane.io           # INSTALLED and HEALTHY both True first
kubectl -n <secret-namespace> create secret generic <secret-name> \
  --from-file=<key>=<credentials-file>                # namespace, name and key: the ProviderConfig's secretRef
kubectl apply -f examples/providerconfig.yaml         # or whatever the project ships instead
kubectl apply -f examples/<kind-lowercase>/<xr-name>.yaml
```

The credentials come from the user or the environment (a file outside the repository, an
exported variable); never write them into a tracked file or a manifest. The ProviderConfig and
the example XR can instead go on the run itself, `--extra-resources=<file>` ("applied after
installing the project"); the Secret stays a `kubectl` command. No ProviderConfig in the project
is a finding to report (author-configuration-package's `providerconfig.md` reference), not
something to invent.

**8. Confirm it reconciled**; don't trust the exit code:

```bash
kubectl get <xr-kind> -A
kubectl describe <xr-kind> <name> -n <ns>    # conditions AND events, also on each composed resource
```

Read what you see as `control-plane-project-charter/references/charter/v2-resources.md`
describes (a missing or wrong ProviderConfig, a resource not reconciled yet, and a kind nothing
reconciles look different). The checks behind those causes:

```bash
kubectl get clusterproviderconfig,providerconfig -A   # does the referenced object exist?
kubectl get providers.pkg.crossplane.io               # INSTALLED and HEALTHY both True?
kubectl get pods -n crossplane-system                 # provider pod running? then its logs
kubectl get crd <plural>.<group>                      # the MR's CRD established?
```

**9. Read the effect back from the provider, not from your own input.** `Ready=True` says
Crossplane finished reconciling, not that the provider holds what you meant: drift, ignored
fields and normalised values all survive it. Before teardown, run the provider's own read for
at least the field the change was about, and quote it:

```bash
aws s3api get-bucket-lifecycle-configuration --bucket <name>
az <service> show -n <name> -g <rg>
gcloud <service> describe <name>
```

Reading values back off the XR, the composed resource's `spec`, or your manifest proves only
that your input round-tripped. Without a provider read, say "reconciled; not independently
verified at the provider".

---

## When a run hangs on "Waiting for package to be ready"

It ends with only `up: error: context deadline exceeded`, which names no control plane and no
package. Do not retry. Check the context first (`up ctx .`): a failed run can leave kubeconfig
on a different control plane, whose healthy package then misleads you. Then diagnose as
`control-plane-project-charter/references/charter/targets.md` ("A run stuck on
`Waiting for package to be ready`") says: the real error is on the `Configuration`, and a pull
failure hands back step 4's choice, never `--public` as a workaround. Report the underlying
condition message, not "the run timed out".
