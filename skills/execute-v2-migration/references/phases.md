# Running the stages

The commands for each stage, the sub-agent briefs, what to do when a step fails, and the final
summary. What changes in each file is in the plan, which points at sections of
`plan-v2-migration` `breaking-changes.md`; read the section before you edit.

## Stage 0: Pre-flight

```bash
test -f .agents/plans/CROSSPLANE_V2_MIGRATION.md || echo "no plan: run plan-v2-migration first"
grep -n '^apiVersion:' upbound.yaml
grep -rl 'kind: CompositeResourceDefinition' apis/ | xargs grep -l 'apiextensions.crossplane.io/v1$'
git status --porcelain
git branch --list migrate-to-v2                 # local
git ls-remote --heads origin migrate-to-v2      # remote; another remote name: `git remote`
```

After the go-ahead, and before any stage runs, whichever stages were asked for:

```bash
git checkout migrate-to-v2                      # it is local
git fetch origin migrate-to-v2 && git checkout --track origin/migrate-to-v2   # only on the remote
git checkout -b migrate-to-v2                   # neither
```

Run the one line that matches, then tick the plan's stage 1 branch item.

From the plan, take: the project name, the counts, each function's language and the test
language, the decisions and assumptions, the dependency targets, and which tests cover which
function. If the plan names no language, detect it with
`control-plane-project-charter/references/languages/README.md`. Read that language file before
stage 5.

## Stage 1: Prepare

```bash
# on migrate-to-v2, checked out in stage 0
# edit upbound.yaml: apiVersion, each dependency version from the plan, apiDependencies if listed
up dep update-cache
up project build
```

Then confirm the models carry the `.m.` groups the functions will import:

| Language | Look for |
|---|---|
| KCL | `.up/kcl/models/io/upbound/awsm/` (the `m` joins the cloud segment) |
| Python | `.up/python/models/io/upbound/m/aws/` |
| Go | `.up/go/models/io/upbound/m/aws/` |

## Stages 2–4: XRDs, compositions, examples

Edit each file with the items the plan lists for it, then `yq '.' <file> > /dev/null`; if it
does not parse, stop and report the file. Edit the YAML structure; don't string-replace whole
blocks: whitespace differs between projects.
If an item is already in its v2 form, tick it and move on.

## Stage 5: Tests, then functions

For each function, in the plan's order:

1. **Tests first.** Hand the [test brief](#test-brief) to a sub-agent. It updates the tests that
   cover the function and runs each with `up test run "tests/<test>"`. Expect red, and read
   why: the failure must name a v2 difference, for example an expected `ec2.aws.m.upbound.io`
   resource the unmigrated function does not emit. A compile error or a missing name is a test
   mistake, not RED: the sub-agent fixes the test and reruns it.
2. **Then the function.** Hand the [function brief](#function-brief) to a sub-agent. It
   migrates the function and runs the language's compile check, then
   `up test run "tests/test-*"`, until every test passes.

   | Language | Compile check, in `functions/<name>/` |
   |---|---|
   | KCL | `kcl lint main.k` — not `kcl main.k`, which runs the module and fails on `option("params")` |
   | Python | `python3 -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" $(find . -name '*.py')` |
   | Go | `go vet ./...` — not plain `go build ./...`, which writes a binary into the function directory |
   | other | the compile or fast-tier row of its `languages/` file |

3. **What no test turned red.** A plan item whose change no updated test detected — a deleted
   `providerConfigRef`, a mapped `deletionPolicy` — gets a test, proven by mutation
   (`control-plane-project-charter/references/charter/tdd.md`), or is reported as not covered.

E2E tests are updated after the functions they exercise, with the same test brief minus the
RED step: they run in stage 7.

## Stage 6: Renames

Only those the plan lists, which follow a deliberate Kind rename:

```bash
git mv functions/<old> functions/<new>
git mv tests/<old> tests/<new>
# then functionRef.name and step in every composition that calls the function
up project build
```

## Stage 7: Verification

1. Hand the [verification brief](#verification-brief) to a sub-agent: the build and every
   composition test.
2. Render one example and read it:

   ```bash
   up composition render apis/<r>/composition.yaml examples/<example>.yaml --xrd apis/<r>/definition.yaml
   ```

   No managed resource may use a legacy provider group, and each carries `forProvider` only,
   unless the project's spec or API sets more (a kept non-`default` `providerConfigRef`, a
   mapped `deletionPolicy`) — `control-plane-project-charter` §5.
3. E2E tests create cloud resources and take long (durations: `e2e-test-configuration`). Run
   them only with the user's go-ahead, through the [E2E brief](#e2e-brief); otherwise the
   summary says "not run".

## Stage 8: Documentation

The plan's items: API versions, namespaced example manifests, connection-secret changes and
commands in the README; the Crossplane version and test paths in CI.

## Sub-agent briefs

A sub-agent does not see this conversation, so each brief names the project root, the
languages, the provider family and the files. Wait for its report. With no sub-agents, follow
the brief yourself (`control-plane-project-charter` §1).

### Test brief

```text
Project root: <path>. Test language: <lang>. Function language: <lang>. Providers: <families>.
Load the `author-tests` skill and `control-plane-project-charter`.

Update these tests to Crossplane v2 before the function they cover is migrated:
<tests>, covering functions/<name>.
The plan's items for them: <items 5.n, verbatim>
What changes in a v2 test: plan-v2-migration breaking-changes.md, section "Tests".

Do not touch functions/<name>. Add providerConfigRef, managementPolicies or a
namespace to an expected resource only where the plan says the function sets it.

Run `up test run "tests/<test>"` for each. Each must fail, and the failure must name a v2
difference (for example an expected .m. apiVersion). A failure for any other reason means the
test is wrong: fix it and run again.

Report: RED as expected | FAILED; files changed; per test, the failure lines that show the v2
difference; anything you could not update.
```

For an E2E test, drop the run step: it runs in stage 7.

### Function brief

```text
Project root: <path>. Function language: <lang>. Providers: <families>.
Load the `author-composition` skill and `control-plane-project-charter`.

Migrate functions/<name> to Crossplane v2 until these tests pass: <tests>. They are already
updated to v2 and fail against the current code.
The plan's items: <items 5.n, verbatim>
What changes: plan-v2-migration breaking-changes.md, sections "Provider API groups",
"deletionPolicy", "providerConfigRef", "Secret references", "Connection secrets".

Keep the function's name and directory: it is the published package name. Never add a
language suffix.
A providerConfigRef naming `default` goes; one naming another config stays, as
{kind: ClusterProviderConfig, name: <n>} unless the plan says otherwise.

Check: <compile check for the language>, then `up test run "tests/test-*"`.

Report: SUCCESS | FAILURE; files changed; per plan item, what you changed; the passed/total
count from the test run's output; anything not done.
```

### Verification brief

```text
Project root: <path>. Load the `verify-configuration` skill and `control-plane-project-charter`.
Build the project and run every composition test. Do not run E2E tests and do not deploy to a
control plane.

Report: build status; composition tests passed/total from the run's output; for each failure,
the test name and its error lines.
```

### E2E brief

```text
Project root: <path>. Load the `e2e-test-configuration` skill and `control-plane-project-charter`.
The user approved creating cloud resources for this run. Run these E2E tests: <names, from
ls -1d tests/e2etest-*> on <local kind | Space <space>/<group>>[, with --public].

Report: passed/total; for each failure, the reason with the resource state and logs.
```

Add `with --public` only when the user chose it; without a target the E2E skill stops.

## When a step fails

| What | Do |
|---|---|
| No plan | Stop: run `plan-v2-migration` first. |
| Branch `migrate-to-v2` exists, locally or on the remote | A previous run. Stage 0 checks it out, tracking the remote one, and resumes with `continue` (interactive: ask first). Never delete it without the user's say-so. |
| `up project build` fails in stage 1 | Check the models for the `.m.` groups (stage 1 table), run `up dep update-cache` again and rebuild. Still no `.m.` models: remove the generated `.up/` (gitignored, the build regenerates it) and rebuild. Still failing: stop and report the dependency versions. |
| `up project build` fails in stage 6 | A rename missed a reference: check that `functionRef.name` and `step` in every composition match the new directory. Still failing: stop and report. |
| An edit's target is not where the plan says | Re-read the file. Already v2: tick it. Otherwise stop and report the file and item. |
| A test sub-agent cannot get RED for the right reason | The test or the plan item is wrong: report it; do not migrate the function against it. |
| A sub-agent reports FAILURE | One retry, with the failure in the brief (interactive: offer it). Fails again: stop and report; interactive options are retry, skip (fix later by hand), abort. |
| Composition tests fail in stage 7 | Stop. Do not run E2E. Report the failing tests; after the fix, resume with `continue`. |
| An E2E run looks stuck | `e2e-test-configuration` has stuck detection; check provisioning and quotas, or run the tests one at a time. |
| A connection Secret is missing on a control plane | The resource the function reads connection details from lacks `writeConnectionSecretToRef`, or a key name is wrong: no render shows either. Check both as `control-plane-project-charter/references/charter/v2-resources.md` says; the function composes the Secret, and a test asserts the reference (`breaking-changes.md`, "Connection secrets"). |

## Final summary template

```markdown
## Migration complete: [project]

Branch: migrate-to-v2

Updated:
- XRDs: [n] → apiextensions.crossplane.io/v2, Namespaced
- Compositions: [n] · Examples: [n] (namespaced)
- Functions: [n] → .m. API groups
- Tests: [n] → v2; RED before each function was migrated: [tests, or "not observed" with why]

Verification (from the runs' own output):
- Build: [status]
- Composition tests: [passed]/[total]
- E2E tests: [passed]/[total] | not run: [why]

Assumptions made: [from the plan and from this run]
Not done: [unticked items, with why]
Rollout risk: [from the plan]

Next: review `git diff main...migrate-to-v2`, commit, open a pull request.
```
