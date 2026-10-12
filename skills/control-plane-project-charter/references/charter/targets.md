# Where a run lands: local KIND or a Space

Facts shared by every command that creates a control plane: `up project run`, `up test run --e2e`, and
`up project stop` finding one again. The procedures stay in the skills that run them
(verify-configuration, e2e-test-configuration); [`control-plane-project-charter` §9](../../SKILL.md#9-never-create-infrastructure-as-a-side-effect)
holds the never-rules. Facts are from the up v0.55.0 source unless marked *observed*.

---

## Which control plane a run uses

The context decides, not a flag (`internal/ctp`, `EnsureDevControlPlane`):

1. `--local` → a local KIND control plane, whatever the context says. It still reads the default up
   profile. With no profile it needs none. A profile with an organization whose login has expired
   fails the run after the full build: `current profile is not logged in or login has expired; run
   up login` (observed with up v0.55.0, `up test run --e2e --local` and `up project run --local`).
   Only the user can fix that (`up login`): report it and don't retry.
2. Otherwise, if the current kubeconfig context resolves to a Space at **any** level — Space, group
   or control plane → a control plane in that Space.
3. Otherwise → local KIND, without saying so.

`--control-plane-group` does not select a Space: from a context outside any Space, a run passing it
still goes local. The first progress line names the result:

```text
Creating local development control plane...          <- local KIND
Creating development control plane in Spaces         <- Space
```

| | Local KIND | Space |
|---|---|---|
| Control plane | kind cluster `up-<project>` (`up project run`) or `<project>-uptest-<test>` (E2E; can be shortened, so read it from `kind get clusters`), plus a registry container `<cluster>-registry` | `ControlPlane` of the same name in the group |
| Package | sideloaded into the local registry; nothing is pushed | pushed to `spec.repository`, then installed |
| Repository, `--public`, group | none of them apply | all of them apply (below) |
| Cloud resources | created, through the test's or project's provider credentials | created |

A local result says nothing about the Space, and the reverse.

## Reading the context (`up ctx`)

Bare `up ctx` is the interactive browser; without a terminal it fails with
`could not open a new TTY: open /dev/tty: device not configured`. The non-interactive forms:

| Command | Does |
|---|---|
| `up ctx .` / `up ctx . --short` | print the current context (prose / bare path) |
| `up ctx ../<name>` | move to a sibling: from a control plane to another one in the same group |
| `up ctx ./<name>` | move into a child: from a group to one of its control planes |
| `up ctx <org>/<space>/<group>[/<cp>]` | absolute path; it must start with the profile's root (`<org>`, or `disconnected/<space>`), otherwise `context "…" is not available in the current profile` |
| `up ctx . -f -` | write the current context's kubeconfig to stdout instead of switching |

A path without a leading `.` is absolute: `up ctx <cp>` from a group does not mean "the control plane
in this group".

**Read the shape of `up ctx . --short`, not its first word.** The first segment is the organization
on Upbound Cloud and the literal `disconnected` on a disconnected Space, so matching
`disconnected/` misses every Cloud Space.

| `up ctx . --short` | Context is at | A run without `--local` lands in |
|---|---|---|
| exits non-zero | no Space: an organization, a non-Upbound context under a Cloud profile, **no profile at all** (every `up ctx` form prints `up: error: unknown profile type`), or a disconnected profile whose Space no longer answers (a raw `dial tcp …/configmaps/ingress-public` error, not a network fault to debug) | local KIND |
| 2 segments: `<org>/<space>`, `disconnected/<space>` | a Space | that Space, group from the kubeconfig namespace, else `default` (below) |
| 3 segments: `…/<space>/<group>` | a group | that group |
| 4 segments: `…/<group>/<control-plane>` | a control plane | its group |

Under a **disconnected** profile, a kubeconfig context that is not an Upbound one resolves to the
profile's own Space when its hub is reachable, so `up ctx .` prints `disconnected/<space>` and runs
go there (source, not measured).

## The group (`--control-plane-group`)

On a Space the group is, in order: `--control-plane-group`; the group in the current context; the
kubeconfig namespace; the literal `default`. So a run from a Space-level context creates a real
control plane in a real group, `default`, not a no-op. The `--help` text ("defaults to the group
specified in the current context") omits the last two steps.

## `--kubeconfig` is an input

`--kubeconfig` (a global flag, "Override default kubeconfig path") names a file `up` **reads** and
never writes. A missing file is rejected at parse time. A file that exists but does not parse
resolves no Space, so the run silently goes local (*observed*: a leftover file holding an error string
turned a Space run into a local one). Write it fresh in this run and check it parses before passing
it:

```bash
KCFG=$(mktemp -t kubeconfig.XXXXXX)
up ctx . -f - > "$KCFG"
kubectl --kubeconfig "$KCFG" config current-context || echo "not a kubeconfig: $KCFG"
echo "kubeconfig: $KCFG"   # pass this path as a value: the variable is gone by your next command
```

Once the run has exited and you are done reading through it, `rm -f <kubeconfig>`: it is this run's
leftover too ([§9](../../SKILL.md#9-never-create-infrastructure-as-a-side-effect)).

`up project run` also **rewrites** the current kubeconfig context to the dev control plane it
created, unless `--no-update-kubeconfig`. After a failed run it can point at a different control
plane than the one you are diagnosing (*observed*): run `up ctx .` before believing `kubectl`.

## Repository visibility and `--public`

On a Space, the run pushes the configuration package to `spec.repository` (or `--repository`), and
each embedded function to its own repository beside it. `up` creates a repository only when **all**
of these hold: it does not exist yet, it is on the Upbound registry, and the login is not a robot
token. A repository it creates is **private** unless `--public` is passed. It never changes an
existing repository.

`--public` ("Create new repositories with public visibility") is accepted by `up test run`,
`up project push`, `up project run` and `up project simulate create`.

| Repository | Without `--public` | With `--public` |
|---|---|---|
| does not exist yet | created private: the install cannot pull it | created public: the install can pull it |
| exists, public | pullable | pullable |
| exists, private | not pullable | **still not pullable**: the flag does not flip an existing repository |

**`--public` publishes the user's package.** Anyone can pull what was pushed, and setting the
repository private later does not take back what was already fetched. Treat it as an irreversible
disclosure, chosen only by the user, never as a debugging step and never as a retry after a hang.

`up repository` has its own traps:

- `up repository create <name>` creates a **public** repository unless `--private` is passed — the
  opposite of what a push creates.
- `up repository update <name>` requires both `--private` and `--publish` as booleans. `--publish`
  is the Marketplace listing policy, not visibility, and the policy string `up repository list`
  prints in its `PUBLISH POLICY` column is not accepted. It asks for confirmation unless `--force`.

## A run stuck on `Waiting for package to be ready`

On a Space, the push and the install are two halves of one run, minutes apart, and the control plane
the run creates gets no pull credential for a private repository. The install fails to unpack what
the push just wrote, the run waits until its timeout (`up project run` default `--timeout 5m`), and
all it prints is:

```text
✗ Waiting for package to be ready
up: error: context deadline exceeded
```

That names neither half. The real error is on the `Configuration`; read it while the control plane
exists:

```bash
up repository get <repository>                     # predicts it: private, and no pull secret on the Space
up controlplane list                                # usually Available/Healthy regardless
up ctx ./<control-plane>                            # from the group context (../<cp> from a sibling)
kubectl get configuration.pkg.crossplane.io
kubectl describe configuration.pkg.crossplane.io <name>
```

On `--local` the same failure has a cause of its own (the last row): read `docker logs <cluster>-registry` first.

| `describe` (`--local`: `docker logs`) shows | Cause |
|---|---|
| `cannot unpack package: … 401 Unauthorized … UNAUTHORIZED: authentication required` | private repository, and no pull credential for it on that control plane (common under a disconnected profile: `up profile list`). Retrying changes nothing |
| `cannot resolve … not found` | pushed to a different repository than the one being installed: reconcile `spec.repository` |
| provider revision unhealthy | a provider still installing, or a bad version constraint: `kubectl get providers.pkg.crossplane.io` and its revisions |
| (`--local`) `open /registry-data/.certs/tls.crt: permission denied`, and the registry container has exited | the run was started under `umask 077`: `up` wrote the registry's certificate with that umask and the non-root registry can't read it (*observed* with `up test run --e2e --local`; `up project run --local` uses the same registry, not observed). Re-run under the default umask; protect a credentials file with `chmod 600` instead |

The ways out of the first row are the user's choice: pull access on the Space (an existing pull
secret or `ImageConfig`), a public repository (`--public`, above), or `--local`, which pushes nothing
and so cannot hit that row — but is not the Space they chose, and has its own cause (the last row).
`--local` is never a silent fallback.

## Teardown and leftovers

- **E2E** tears its control plane down after every test that got past setup, pass or fail, unless
  `spec.skipDelete: true` or `--skip-control-plane-cleanup`. On `--local`, a setup failure after kind
  has created the cluster, or a panic (an `E2ETest` without `timeoutSeconds`), skips teardown
  silently. The cluster, its registry container and its registry directory stay behind (observed
  with up v0.55.0; e2e-test-configuration's `local.md`, Leaks). kind cleans up after a failure
  inside its own create.
- **`up project run`** leaves its control plane running. `up project stop` from the project root
  removes it — for a local one, the kind cluster, its registry container and the registry directory.
  It finds the control plane the same way a run does, so pass `--local` when the context is a Space;
  it asks for confirmation unless `--force`. It deletes nothing on the control plane first (below).
- **`kind delete cluster --name up-<project>` leaves `up-<project>-registry` running** (*observed*).
  Remove it with `docker rm -f -v up-<project>-registry`.

### Delete the XRs, and wait, before the control plane

Deleting a control plane leaves every cloud resource its managed resources created. A provider
deletes the external resource only when the managed resource is deleted while the provider still
runs; `up project stop`, `kind delete cluster` and `up controlplane delete` take the providers
with them, and what they managed stays in the cloud, billed and tracked by nothing. `up project
stop` deletes nothing on the control plane first (up v0.55.0 source). E2E's own teardown does
delete the test's resources first, so this is yours after `up project run`, after a run you
stopped or that was killed, after `skipDelete: true` or `--skip-control-plane-cleanup`, and before
you delete a leaked cluster.

With a kubeconfig for the control plane this run created (local: `kind get kubeconfig --name
<cluster>`; Space: `up ctx ./<control-plane> -f -` from its group, as for any read):

1. **Delete the XRs this run applied**, the test's `spec.manifests` or the examples you applied:
   `kubectl --kubeconfig <kubeconfig> delete <xr-kind> <name> -n <ns> --wait=false`.
2. **Wait, bounded, until no managed resource is left.** Each disappears once its provider has
   deleted the external resource and removed its finalizer:

   ```bash
   for _ in $(seq 1 60); do
     out=$(kubectl --kubeconfig <kubeconfig> --request-timeout=10s get managed -A --no-headers) &&
       [ -z "$out" ] && break
     sleep 10
   done
   kubectl --kubeconfig <kubeconfig> get managed -A    # expect: No resources found
   ```

   `the server doesn't have a resource type "managed"` means no provider was ever installed, so
   nothing reached the cloud.
3. **Only then delete the control plane:** `up project stop` (add `--local` when the context is a
   Space), `up controlplane delete <name>` on a Space, or, for a leaked kind cluster, as
   e2e-test-configuration's `local.md` (Leaks) says.

**If managed resources remain after the wait, deletion is hanging.** Usually the provider can no
longer authenticate, or the cloud refuses (a dependency still attached, deletion protection).
Don't delete the control plane, and don't remove a finalizer to finish the job: either way the
cloud resource stays and nothing records it any more. List what remains, with no Secret data:

```bash
kubectl --kubeconfig <kubeconfig> get managed -A -o custom-columns='KIND:.kind,NAMESPACE:.metadata.namespace,NAME:.metadata.name,EXTERNAL-NAME:.metadata.annotations.crossplane\.io/external-name'
kubectl --kubeconfig <kubeconfig> describe <kind> <name> -n <ns>   # Synced condition and events: why
```

Report each one by kind, external name and the names or tags the run gave it, so the user can
find it in the cloud, and leave the control plane running: it is the only thing still able to
delete them. Interactive, ask whether to fix the cause and let the providers finish, or delete
the control plane and remove the resources in the cloud by hand; unattended, report the control
plane as left running, and why.

**E2E's teardown does not wait forever either.** It deletes the test's resources for up to
`cleanupTimeoutSeconds`, then deletes the control plane whatever remains (up v0.55.0 source).
`Cleanup summary: N deleted, M remaining` with `M` above 0 means `M` of the test's resources went
with the control plane, and every managed resource among them left its cloud resource orphaned:
the `Resource cleanup details` table after it gives each one's `NAME` and `EXTERNAL-NAME`. Report
them as leftovers to remove in the cloud. `N` counts only what was left when `up`'s cleanup
started, after the test's own delete step (source), so `0 remaining` doesn't show that every
cloud resource is gone: only a check in the provider's API does.

To stop an E2E run early and still get that teardown, send `up` one interrupt
(`kill -INT <pid>`) and wait for it to exit: it prints `Interrupted. Cleaning up; interrupt again
to abort.` and tears down (source; it may first finish the step it is in). A second signal, a
SIGKILL or a harness that kills the process skips the teardown, and the steps above are yours.
