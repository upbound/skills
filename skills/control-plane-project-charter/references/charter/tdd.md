# The inner loop, and backfilling tests

How to iterate without paying a full build every time, and how to add tests to code that already works. [`control-plane-project-charter` §3](../../SKILL.md#3-develop-test-first-red--green--refactor) states the discipline.

## The two-tier inner loop

**Every `up test run` pays a full project build** — schema generation, dependency check,
function build, package build, push to the local daemon. There is no flag to skip it;
`--no-build-cache` only makes it slower. Measured wall time **per `up test run`**, one function:

| Project | Warm cache | Cold (dependencies pulled) |
|---|---|---|
| KCL | ~12–16 s | minutes |
| Python, embedded | 11–50 s, scaling with the number of test cases (11 s for two, 36 s for six) | minutes |

These are composition-test runs. E2E durations are in e2e-test-configuration's `local.md` and
`space.md` references.

Use both tiers:

| Tier | ~time | Catches |
|---|---|---|
| Fast — run the function body directly, if the language offers a way (see [`languages/`](../languages/); Python: `run_function.py`, Go: `go test ./...` against `RunFunction`) | ~1s | exceptions, wrong resource count, missing fields, the minimal-XR branch |
| Assertion — `up test run "tests/<t>"` | tens of seconds warm, minutes cold | everything the suite asserts — this is the one that goes RED and GREEN |

The fast tier never replaces the RED/GREEN cycle: Python's asserts nothing, and Go's unit tests
run no pipeline. It saves you a whole build to find a typo.

## Backfilling tests for code that already exists

Migrations, coverage work and "add a test for this" all start from working code, so there is
no natural RED. That is fine, but a test written against passing code has never been
observed to fail, and is where false coverage claims come from.

**Prove it can fail with a deliberate mutation.** Break what the test should catch, confirm
*that test* goes red while the others stay green, then restore the file. Copy it out first, and
restore from that copy:

```bash
keep=$(mktemp -d) && cp <file> "$keep"/ && echo "copy: $keep"   # the variable is gone by the next command
```

1. Mutate `<file>` with your editor or file-edit tool (delete the field, move the block below
   an early return, ...). This is an edit, not a command, so the steps are not one script.
2. `up test run "tests/test-*"`: expect exactly the new test to fail, naming the right field.
3. Restore and check the restore, using the printed path:
   `cp <copy-dir>/<name> <file> && cmp <copy-dir>/<name> <file> && rm -rf <copy-dir>`.
4. `up test run "tests/test-*"`: expect green again.

**Restore from the copy, not from git.** `git checkout -- <file>` puts back the last commit and
discards every uncommitted change in the file, not only the mutation: mutate a file holding the
function you just wrote, uncommitted, and that revert deletes it, and a file git doesn't track
has nothing to revert to. The copy is the file exactly as it was before the mutation, whether it
is committed, modified or untracked. `git stash` doesn't help either: it takes the uncommitted
code out of the tree you are testing.

Don't revert by editing back: `up test run`, like `up project build`,
`up test generate` and `up dep add`, rewrites `upbound.yaml` whenever it has a dependency and
drops its comments (author-configuration-package, Phase 4), so a mutation commented out there
cannot be found again.

**Mutate the implementation, never the test's expected value.** Changing the expected value
turns any test red, including one that asserts nothing the code does, so it proves only that
the comparison runs. The mutation has to be the regression the test exists to catch.

Report which mutation you used and which tests it turned red. *"Moving the lifecycle block
below the versioning guard turned test 3 red and left the other three green"* is a coverage
claim with evidence behind it. *"Coverage: complete"* is not.

If a mutation you expected to break the test leaves the suite green, the test does not cover
what you thought — say so rather than reporting the coverage.

## Distinguishing inputs

**Check that each pass-through input is distinguishing.** For every field the function copies
from the XR (region, a config name, a CIDR, the XR's own name), hard-code the field to the
test's input value — the default, where a test relies on it — and run the suite. If it stays
green, every test feeds that same value and the input isn't distinguishing: give one test a
value that differs from the default and from every sibling field, and see it go red under the
same mutation. Reading a sibling field instead (the XR name in place of the config name) must
go red too.
