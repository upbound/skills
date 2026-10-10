# Language references

One file per language, shared by every skill in this plugin, covering composition functions and
tests. Language-neutral rules are in [`control-plane-project-charter`](../../SKILL.md), not here.

## Detecting the language

Detect each directory on its own: the composition language from `functions/<n>/`, the test
language from `tests/<n>/`; a project may mix them. The markers are the ones `up` checks
(up v0.55.0), in its order — **the first match wins**:

| Directory contains | Language | Functions: read | Tests: read |
|---|---|---|---|
| `pyproject.toml` **and** a `function/` dir (functions); `pyproject.toml` (tests) | Python, SDK layout | [`python.md`](python.md) + [`python/`](python/) | [`python/tests.md`](python/tests.md), [`python/test-templates.md`](python/test-templates.md) |
| `kcl.mod` | KCL | [`kcl.md`](kcl.md) + [`kcl/`](kcl/) | [`kcl/tests.md`](kcl/tests.md) |
| `main.py` | Python, embedded layout | [`python.md`](python.md) + [`python/`](python/) | [`python/tests.md`](python/tests.md), [`python/test-templates.md`](python/test-templates.md) |
| `go.mod` | Go | [`go.md`](go.md), [`go/functions.md`](go/functions.md) | [`go.md`](go.md), [`go/tests.md`](go/tests.md) |
| only `*.gotmpl` / `*.tmpl` files (subdirectories allowed) | go-templating | [`go-templating.md`](go-templating.md) | [`go-templating.md`](go-templating.md) |
| `test.yaml` (tests only) | YAML | — | [`yaml.md`](yaml.md) |
| `package.json` / `*.ts` (functions) | TypeScript: `up` has no builder, so `up project build` fails with `no suitable builder found` | [`typescript.md`](typescript.md) — its header says how these projects are built | — (no TypeScript test language) |

Order matters in two places. For **tests**, `kcl.mod` is checked first and `pyproject.toml` before
`main.py`; for **functions**, the Python SDK layout (`pyproject.toml` plus `function/`) is checked
before `kcl.mod`. A Python SDK function also has `function/main.py`; only a `main.py` at the
directory root means embedded.

A test directory that matches no row is skipped without a message. One that matches but produces
no `CompositionTest` or `E2ETest` — a Go program printing `items: []` — contributes zero tests
(charter §8).

## Choosing the test language for new tests

The language of *new* tests is a choice, not a detection.
[`control-plane-project-charter` §10](../../SKILL.md#10-language-dispatch) states the rule; the
detail:

1. Tests already exist in the project → write new ones in the same language. Only a test dir
   that produces a `CompositionTest` or `E2ETest` counts. A program that emits none — a Go
   program printing `items: []`, a linter over repo files — is not a test (charter §8) and does
   not set the language.
2. Otherwise use the **composition language**, whenever `up` supports it as a test language:
   `kcl`, `python`, `go`, `go-templating` — every language `up function generate` produces.
   Why: one toolchain and one set of idioms per project, whoever maintains the function can
   maintain its tests, and typed languages check expectations against the function's own models.
   Pass the language to the generators:
   `up function generate <n> <composition-path> --language go`, then
   `up test generate <n> --language go`. `up project init --scratch` creates neither and ignores
   `--language`; only a `--template` project takes `--language` and `--test-language` at init,
   and the templates differ in Crossplane generation: check the XRDs' `apiVersion`
   ([`charter/generators.md`](../charter/generators.md)).
3. Otherwise **YAML** — the fallback for TypeScript functions (the CLI has no TS test
   language) and projects with no embedded function. `up project init` does not accept
   `--test-language yaml`; scaffold YAML tests with `up test generate <n> --language yaml`.
