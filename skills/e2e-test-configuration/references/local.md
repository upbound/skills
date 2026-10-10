# Running E2E on a local kind control plane (`--local`)

Read before running `up test run --e2e --local`. [SKILL.md](../SKILL.md) has what both targets share:
preconditions, the run idiom, stuck detection and the report. Facts below come from the up v0.55.0 source and
runs, and may change between versions.

## Preconditions

- **Docker must be reachable** (`docker info` exits 0). `up` creates the cluster itself through the kind
  library; you need the `kind` CLI only to look inside or clean up.
- **List `kind get clusters` and `docker ps -a` before the run, and keep the lists.** Anything already there
  is not this run's, even with this project's `<project>-uptest-` name (SKILL.md, Never): report it.
- **Don't run `up ctx`, or check a repository, `--public` or the group.** `--local` needs no context or
  profile, and it sideloads the package instead of pushing it
  (`control-plane-project-charter/references/charter/targets.md`), so a failing `up ctx . --short` is not a
  failed precondition here. It does read the default up profile: see targets.md, "Which control plane a run
  uses".
- **Credentials are a static Secret** in `extraResources`: `credentials.source: Secret` plus
  `secretRef: {namespace, name, key}`, built from a `UP_*` variable. `source: Upbound` web identity does not work
  on kind. The shapes, the AWS credentials-file format and how to build it in memory are in author-tests'
  `e2e.md` reference.
- **Why the default umask (SKILL.md Phase 2).** `up` writes the local registry's TLS certificate and key
  (`/tmp/up-local-registry/<cluster>/.certs/`) with your umask, and the registry container runs as a
  non-root user. Under `umask 077` it can't read them and exits; the run waits at `Waiting for package to
  be ready` until `context deadline exceeded`, about 10 min later (observed with up v0.55.0). `docker logs
  <cluster>-registry` shows `open /registry-data/.certs/tls.crt: permission denied`. To protect a credentials
  file, `chmod 600` that file; better, write no file at all.
- **A leftover kind cluster can exhaust the host's inotify instances.** On a Linux host with
  `fs.inotify.max_user_instances` at 128, two kind clusters used them up: kube-proxy logged
  `too many open files`, and the run failed at `✗ Creating local development control plane` when the
  Crossplane install timed out (observed once with up v0.55.0). A cluster from another run is not yours to delete
  (above), and the limit is the host's setting: report both.

## Target flags

```bash
up test run "tests/e2etest-<n>" --e2e --local
```

inside the run idiom in SKILL.md Phase 4. Optional:

- `--control-plane-version <version>` pins UXP (otherwise `spec.crossplane.version`, otherwise the latest
  stable UXP).
- `--skip-control-plane-cleanup` keeps the cluster after the test. Deleting it, its managed resources first
  (`control-plane-project-charter/references/charter/targets.md`, Teardown and leftovers), and checking the
  cloud are then yours to do or to report.

## What the run does

1. Creates a kind cluster whose name starts `<project>-uptest-` (shortened: below) on the node image
   `xpkg.upbound.io/upbound/kind-node`: Kubernetes v1.37.0 with up v0.55.0. It also starts a local OCI registry
   container (`upbound/olareg`).
2. Installs UXP: `spec.crossplane.version` or `--control-plane-version` if set, otherwise **the latest stable
   UXP**. `spec.crossplane.autoUpgrade.channel` is ignored on this path.
3. Sideloads the built package into the local registry.
4. Applies `initResources`, **then** installs the Configuration and waits for its packages, **then** applies
   `extraResources` (Namespace, Secret, ProviderConfig) without waiting for them.
5. Applies the manifests and asserts `defaultConditions` within `timeoutSeconds`.
6. **Tears down after every test that got past setup, pass or fail:** the test's resources, then the kind
   cluster, the registry and its directory. `spec.skipDelete: true` or `--skip-control-plane-cleanup` skips it,
   and so, silently, does a setup failure or a panic ([Leaks](#leaks)).

The first progress line is `Creating local development control plane...`.

## Timings (observed with up v0.55.0)

| What | Observed |
|---|---|
| Whole run, a small VPC network (cleanup summaries counted 2–7 resources) | ~5–10 min |
| `chainsaw/apply` step | 79–258 s |
| `timeoutSeconds` that test set | 1200 (the Go scaffold writes 300) |

Size `timeoutSeconds` to what you provision (author-tests' `e2e.md` reference); an EKS cluster needs far more.

## Reaching the cluster while it runs

The cluster exists only during the run. Its name is `<project>-uptest-<test>` shortened: observed with up
v0.55.0, a 56-character name became its first 49 characters, ending in `-`. Don't derive it, and don't wait on
a word such as `cluster`: find it with `kind get clusters`, the entry starting `<project>-uptest-` that was not
in your list from before the run. The registry container is `<cluster>-registry`.

```bash
kind get clusters                                   # the new entry starting <project>-uptest-
KCFG=$(mktemp -t kubeconfig-e2e.XXXXXX)
kind get kubeconfig --name <cluster> > "$KCFG"
kubectl --kubeconfig "$KCFG" get managed -A
echo "kubeconfig: $KCFG"   # reuse the path as a value: the variable is gone by your next command
```

Once the run has exited, `rm -f <kubeconfig>`: the cluster it points at is gone, and the file is this run's
leftover (charter §9).

Use `kind get kubeconfig`, not a kubeconfig `up` leaves in `/tmp`: observed with up v0.55.0,
`/tmp/up-*.kubeconfig` was empty (0 bytes), and the test's own `/tmp/<test><random>/kubeconfig.yaml` was gone by
the next read.

If the run never got past the package install, check that before tracing any managed resource:
`docker logs <cluster>-registry` (the umask precondition), then `kubectl get pkgrev -o wide` and `kubectl
describe configuration`. Then use the brief in [troubleshooting.md](troubleshooting.md).

### Reading a status during the run (an `E2ETest` can't assert one)

An `E2ETest` can't assert a status field or condition (author-tests' `e2e.md` reference). To read one, take
it inside the one run you need anyway, and **watch rather than poll**: the delete starts about a second after
the assert sees `Ready` (observed with up v0.55.0), so a read every few seconds misses the one moment the
status is complete. Wait, bounded, until the XR exists, then watch that one object (`get managed -w` fails:
`managed` is a category), bounded too:

```bash
for _ in $(seq 1 60); do                            # until the XR exists, or the run ends
  grep -q '^EXIT=' /tmp/e2e-<n>.log && break
  kind get kubeconfig --name <cluster> > <kubeconfig> 2>/dev/null &&
    kubectl --kubeconfig <kubeconfig> --request-timeout=5s get <xr-kind> <xr-name> -n <namespace> >/dev/null 2>&1 &&
    break
  sleep 5
done
kubectl --kubeconfig <kubeconfig> --request-timeout=600s get <xr-kind> <xr-name> -n <namespace> -w \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status} {.status}{"\n"}' >> /tmp/e2e-<n>-status.txt 2>&1
grep '^True ' /tmp/e2e-<n>-status.txt | tail -1      # the last read taken while Ready
```

The watch prints one line per change and ends with the cluster or after 600 s: on a watch, kubectl applies
`--request-timeout` to the whole response, so it is the watch's time limit (stock macOS has no `timeout`).
Size it to one command's timeout, never to the few seconds other calls get, and if it ends before `EXIT=` is in
the log, start it again (it prints the current state first). Give every other `kubectl` call
`--request-timeout`: one without it hung for 150 s once the cluster was gone. A composed resource is read the
same way, one watch per object.

Quote it as **"read-back, not asserted"**, with its `Ready` condition: a read while `Ready` is `False` can be
partial. It is not a provider read. If the window was missed, report "not read back" rather than re-running a
green e2e just for the read ([SKILL.md](../SKILL.md), Never). It is report evidence, never a pass condition
(author-tests' `e2e.md` reference).

The resource tables the log prints during the assert are progress output, not a read-back: in the runs observed
with up v0.55.0, none showed the XR `Ready` although the assert passed. Quote the assert's `PASS` line, never a
table as a resource's state.

### A provider read

A provider read (the cloud's own API, by the resources' external ids) works from the moment those ids
appear, in the XR's status or on the managed resources, until the assert sees `Ready`: nothing deletes the
resources before then. Take it as soon as the ids appear, not at `Ready`: a read taken at `Ready` raced the
delete and got NotFound (observed once with up v0.55.0).

## Evidence and cleanup

After the run the cluster is gone, so `kubectl get managed` no longer works. The evidence is:

- **The log's `Cleanup summary: N deleted, 0 remaining` line**, quoted. A remaining count above 0 means the
  cluster was deleted with managed resources on it: their cloud resources are orphaned (what `N` counts
  and what to report: `control-plane-project-charter/references/charter/targets.md`, Teardown and
  leftovers).
- **A provider read taken during the run**, quoted. Without one, the report says "not verified at the
  provider".
- **Leftovers, checked in the provider's API** by the names or tags the test used, not in Kubernetes. Don't
  assume a provider CLI exists: `command -v <cli>` first, then use whatever is installed (observed: no `aws`
  CLI, but an SDK such as boto3). If neither is available, say the leftovers were not checked.
- **`kind get clusters`** lists no `<project>-uptest-*` cluster beyond those in your list from before the run.

## Leaks

- **A setup failure leaks the cluster, silently.** Once kind has created the cluster, any later setup failure
  makes `up` skip teardown with no message. The failures include the UXP install (a bad
  `--control-plane-version` or Helm value), the license, the pull secret, the registry, the image config,
  `setupTimeoutSeconds` running out, or an interrupt during `Creating local development control plane`. The
  kind cluster, `<cluster>-registry` and `/tmp/up-local-registry/<cluster>/` stay behind (observed with up
  v0.55.0: `✗ Creating local development control plane`, and no `Tearing down` line). kind cleans up after a
  failure inside its own create. An `E2ETest` without `timeoutSeconds` panics after setup (exit 2) and leaks
  the same way, as does a run killed by a command timeout. After any run whose log has no
  `Tearing down test control plane` line, run `kind get clusters` and `docker ps -a`.
- **Remove only what this run created:** the cluster `kind get clusters` lists for this run, with
  `kind delete cluster --name <cluster>`, and only once no managed resource is left on it: delete its XRs and
  wait first (`control-plane-project-charter/references/charter/targets.md`, Teardown and leftovers). Anything
  else on the machine is the user's.
- **`kind delete cluster` leaves the registry container behind**
  (`control-plane-project-charter/references/charter/targets.md`). If you delete a leaked cluster by hand, check
  `docker ps -a` for this run's registry container (`upbound/olareg`) and remove it with
  `docker rm -f -v <container>`, then `rm -rf /tmp/up-local-registry/<cluster>`.
