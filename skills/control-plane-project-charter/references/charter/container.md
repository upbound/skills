# The container boundary

[`control-plane-project-charter` §7](../../SKILL.md#7-the-container-boundary) states the rule.

---

**Every `up test run` first runs the test program in every matched directory** — the
`Parsing tests` step, before any render and before any control plane exists. Where that program
runs, and which environment it sees, depends on the test language (up v0.55.0 source):

| Test language | Where generation runs | What it sees |
|---|---|---|
| KCL | container (`kcl run -o test.yaml`) | only `UP_*` variables, no `~/.aws` |
| Python, embedded (`main.py`) | container (`uptestpyrunner`) | only `UP_*` variables, no `~/.aws` |
| Python, SDK (`pyproject.toml`) | container (`hatch run test`) | only `UP_*` variables, no `~/.aws`; the project at `/project`, CWD `/project/tests/<dir>` |
| Go | **locally** — `go mod tidy` then `go run .`, in the test dir | your full environment and your real files |
| go-templating | **locally** — in-process, inside `up` | `up`'s own environment, through Sprig's `env` |
| YAML | **locally** — in-process, no container | nothing; static YAML reads no input |

**Name every test input `UP_*`, in every language.** KCL and Python need the prefix; Go does not,
but a Go test written that way ports to the other languages unchanged, and one `grep` for `UP_`
finds everything the suite needs before a run.

For KCL and Python, two consequences:

1. **`~/.aws`, `~/.config/gcloud` and `~/.azure` are not mounted.** Nothing that reads a
   credentials file or a cloud CLI's config finds anything, so a default credential chain
   resolves to nothing inside that container.
2. **Only environment variables whose names start with `UP_` are passed in.** The runner
   filters the environment on that prefix. `AWS_ACCESS_KEY_ID`, `AZURE_CREDENTIALS`,
   `GOOGLE_APPLICATION_CREDENTIALS` — all absent, whatever your shell has exported.

So a credential reaches a generated manifest by one portable route: **export it under a `UP_`
name in the same command as the run, and read that name in the test module.** A variable
exported in an earlier command is gone by the next one.

```bash
export UP_AWS_CREDENTIALS="<credentials file contents>"   # build it as author-tests' e2e.md shows
up test run "tests/e2etest-<n>" --e2e <target flags>       # --local, or a Space's: e2e-test-configuration
```

**Read the variable in a way that fails loudly when it is missing.** A silent fallback to
`""` generates a syntactically valid Secret holding nothing; the run then goes all the way to
provisioning a control plane and real resources before the provider rejects the empty key.
Failing at manifest generation costs about a second and names the variable you forgot.

**That is safe only if the composition gate never runs an e2e program** (§7). `up test run`
filters by kind only after running every matched program, so split the runs by directory prefix:

```bash
up test run "tests/test-*"                             # composition gate: no e2e program runs
up test run "tests/e2etest-<n>" --e2e <target flags>   # E2E: fails fast on a missing input
```

Write both commands in the project README, so nobody uses `tests/*` as the gate. **Unless the
project's own gate (a Makefile target, CI, its README) runs `up test run tests/*`**: then keep
it, and that run needs the e2e inputs set too. Without `--e2e` no E2E test executes, so a program
that only checks its input is set passes with any non-empty value (observed with up v0.55.0); with
it, the composition tests the same programs emit are dropped (`up test run --help`). Say
so in the README beside that command, and in your report as a departure from the `tests/test-*`
default.

An `e2etest-*` run without `--e2e` stops with `unable to validate composition tests: no valid
CompositionTests found` (§7).

Prefer web identity (`source: Upbound`) wherever the platform supports it — no credential
crosses the boundary at all, and this whole section stops applying.

**There is a second, tighter boundary.** Rendering runs each composition function as a Docker
container, in *every* language including Go. Nothing mounts a host path into those containers,
and by default nothing forwards your shell environment into them — a composition function never
sees your credential files, whatever the table above says about its tests.

Two routes in are deliberate: a test's `functionCredentialsPath`, a file of Secrets for the
pipeline steps' `credentials`, and the `render.crossplane.io/runtime-docker-env` function
annotation, set with `up test run --function-annotations render.crossplane.io/runtime-docker-env=KEY=VALUE`,
which injects explicit `k=v` pairs and nothing else. If a function needs a value at render time,
use one — not an env var you exported and hoped would arrive.
