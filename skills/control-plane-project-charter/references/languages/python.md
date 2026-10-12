# Python

Everything Python-specific for a control-plane project: composition functions and tests. The
language-agnostic rules are in [`control-plane-project-charter`](../../SKILL.md); this file and
[`python/`](python/) say how Python expresses them.

The helper scripts ship with the `author-composition` skill, not the project. Write their full
path, from that skill's directory, into every command: a shell variable set in one command is
gone by the next.

```bash
# A wrong path makes every call below die with a bare "No such file".
[ -f <author-composition>/scripts/probe_project.py ] || echo "probe_project.py not found — pass its path explicitly"
```

| | |
|---|---|
| Scaffold a function | `up function generate <n> [<composition-path>] --language python` |
| Scaffold a test | `up test generate <n> --language python`: writes `tests/test-<n>/` (with `--e2e`: `tests/e2etest-<n>/`); the CLI prepends the prefix itself, so do not pass it |
| Set up the venv, first | `python3 <author-composition>/scripts/setup_venv.py --project <root>`, right after the first `up project build` ([below](#set-up-the-venv-first)) |
| Probe the project | `python3 <author-composition>/scripts/probe_project.py --project <root> [<Kind>…]`: layout, import prefix, import lines, class names. Standard library only |
| A Kind's fields | `python3 <author-composition>/scripts/probe_project.py --project <root> --fields <Kind>`: every `forProvider` field, list fields with misleadingly singular Upjet names (`attribute`, `globalSecondaryIndex`) flagged, and the cross-resource `*Ref`/`*Selector` fields. Its first line reports the project's generation |
| Fast inner loop | `python3 <author-composition>/scripts/run_function.py --project <root> --minimal examples/<kind>/<xr-name>.yaml`: needs the venv. XRD defaults are not applied (unlike `up test run` with `xrdPath`), so give every required field, defaulted ones included |
| Function unit tests | `.venv/bin/python -m unittest discover -s functions/<n>/tests -t functions/<n>`; layout and template in [`python/tests.md`](python/tests.md#function-unit-tests) |

## Where everything is

| File | What is in it |
|---|---|
| [`python/imports.md`](python/imports.md) | deriving the import path for any Kind, and the class names inside a generated model |
| [`python/patterns.md`](python/patterns.md) | the function bootstrap, building a managed resource, tag maps, `resource.update()` clobbering, optional XRD objects, namespaces, XRD schemas that generate clean models, a Fatal result |
| [`python/readiness.md`](python/readiness.md) | observed resources by composition key, connection Secrets, ProviderConfig readiness, safe conditional creation, the early-return chain |
| [`python/tests.md`](python/tests.md) | the coverage shapes in Python syntax, the dump modes, assertion rules, function unit tests |
| [`python/test-templates.md`](python/test-templates.md) | composition-test and E2E-test templates, SDK and embedded |
| [`python/examples.md`](python/examples.md) | two complete functions and an `upbound.yaml` |
| [`python/pitfalls.md`](python/pitfalls.md) | mistakes that give a green run and a broken platform, and the errors they print |

## Set up the venv first

Run `setup_venv.py` once, before you write any function or test code, right after the first
`up project build` (which generates the models it installs). It takes about 11 s. Re-run it when
you add a function or test directory; not after `up project build` (see "Models last" below).

**Why, when the function never runs on your host:** the fast tier needs it, and without it an
editor underlines every correct import, inviting a "fix". A project with no venv still builds
and goes green, so skipping it is the common mistake.

| What | Runs where | Needs the venv |
|---|---|---|
| The function, under `up test run` / `up project build` | container | no |
| `probe_project.py` | host | no |
| `run_function.py` (fast tier) | host | yes |
| Your editor's language server | host | yes |

**Build it from the project's own pins, not by package name.** `pip install
crossplane-function-sdk-python` gets the newest release, and `resource.update()` has changed
across versions: up to 0.12.0 it serializes with `exclude_defaults`, from 0.13.0 with
`exclude_unset` (and `by_alias`); 0.5.0 and 0.6.0 also drop an unset `apiVersion`/`kind`,
0.7.0 onwards add them back. `up function generate` (v0.55.0) pins 0.11.0. A fast tier running
a different serializer from the container is not a proxy for the real run.

`setup_venv.py` creates `.venv` at the project root, installs every function and test directory
from its own pins, installs the generated models editable and last, checks the imports resolve,
and writes `.vscode/settings.json`. By hand, and why each step matters:

```bash
# Every generated pyproject.toml declares requires-python ">=3.11,<3.14"; python3 is often 3.14.
PYBIN=$(for v in 3.13 3.12 3.11; do command -v python$v && break; done)
"${PYBIN:?no supported Python found}" -m venv .venv
.venv/bin/pip install --upgrade pip                      # see below
(cd functions/<fn> && ../../.venv/bin/pip install -e .)  # SDK layout; the cd is load-bearing
.venv/bin/pip install -r functions/<fn>/requirements.txt # embedded layout
(cd tests/<t> && ../../.venv/bin/pip install -e .)       # every test dir, likewise
.venv/bin/pip install -e .up/python                      # the models: last, editable
.venv/bin/pip install pyyaml                             # run_function.py reads examples
```

- **The `cd` is load-bearing.** pip resolves `crossplane-models @ file:./../../.up/python`
  against the current directory, not the pyproject's. From the project root it fails with a
  "No such file or directory" naming a path two levels above the project.
- **Upgrade pip.** The pip in a fresh 3.11 venv (23.2.1) cannot parse that relative
  requirement and fails with `InvalidRequirement: Invalid URL given`, which reads as a broken
  project.
- **A venv on the wrong interpreter is worse than none.** `python3.14 -m venv .venv`
  succeeds; every install then fails with `Package '...' requires a different Python: 3.14.4
  not in '<3.14,>=3.11'`, and the empty `.venv` left behind is what VS Code picks up. A venv
  cannot be re-pointed: `rm -rf .venv` and rebuild. `setup_venv.py` reads the constraint first,
  picks the newest matching `python3.N`, and replaces a venv that does not match
  (`--no-recreate` reports instead).
- **Models last, editable.** Each function and test pyproject depends on `crossplane-models`,
  so installing one copies the models into `site-packages` over an editable install; `pip list`
  still shows the package, but a regenerated model is invisible. Installed last and editable,
  pip writes a `.pth` pointing at `.up/python`, so after `up dep add` and `up project build` a
  new module (`models.io.upbound.m.aws.kms.key.v1beta1`) resolves with no pip step.

**In the editor**, the interpreter is all it needs; `setup_venv.py` writes the settings and
silences the one noisy scaffold diagnostic (`RunFunction` overrides `FunctionRunnerService`).
If an import still shows unresolved, check it with `probe_project.py` rather than changing it.

## Layout: SDK or embedded

Two layouts are current. Match the one the project uses; never convert one to the other.

| | SDK | Embedded |
|---|---|---|
| Function | `functions/<n>/function/fn.py`: a `FunctionRunner` class with `async def RunFunction(self, req, _)` | `functions/<n>/main.py`: `def compose(req, rsp)` |
| Test | `tests/test-<n>/test/__main__.py`: builds the tests and ends with `print(yaml.dump({"items": [...]}))` | `tests/test-<n>/main.py` (+ `resources.py`): module-level `CompositionTest` objects; no `items`, nothing printed |
| Model import | `from models.io…` (installed package) | `from .model.io…` (the `model` symlink) |
| Dependencies | `pyproject.toml` (hatch) with `crossplane-models @ file:./<rel>/.up/python` | `requirements.txt` + the `model -> ../../.up/python/models` symlink |
| Produced by | `up function generate`, `up test generate --language python` (up ≥ v0.50.0; earlier versions generate the embedded layout) | `up project init` language templates (e.g. AWS Bucket + Python) |

How `up` picks the builder differs between functions and tests:

| | SDK when |
|---|---|
| Function | the directory has both a `pyproject.toml` and a `function/` subdirectory; otherwise a `main.py` at the function root selects the embedded builder. The SDK layout also has `function/main.py`, so only a root `main.py` means embedded |
| Test | the directory has a `pyproject.toml` (checked before `main.py`) |

The test directory decides for tests, so a project can mix SDK functions and embedded tests.
Both layouts build one function image that the composition's `functionRef` references.
`probe_project.py` reports the layout per directory:

```text
function  functions/compose-bucket     layout=embedded  import prefix='.model.'
test      tests/test-storagebucket     layout=embedded  import prefix='.model.'
```

**Create scaffolds with the CLI; never hand-write `pyproject.toml` or the package layout.**
Then edit only the logic files. Two limits:

- **The CLI has no embedded templates.** `up test generate --language python` in an embedded
  project writes an SDK test, so the tree ends up with both layouts. In an embedded project,
  copy an existing test directory instead.
- **`.up/python` must exist before `up function generate` / `up test generate`.** The
  `crossplane-models` dependency is written into the new `pyproject.toml` only when the schemas
  already exist; `up project build`, `up dependency add` and `up xrd generate` create them.
  Otherwise add `"crossplane-models @ file:./../../.up/python"` to `dependencies` yourself (the
  one edit to a generated pyproject you may need), run `up project build`, and re-run
  `setup_venv.py`. A missing line breaks imports; it does not change which builder `up` picks.

The function bootstrap is in [`python/patterns.md`](python/patterns.md), the test shapes in
[`python/test-templates.md`](python/test-templates.md).
