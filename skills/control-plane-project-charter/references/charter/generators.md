# What the CLI generators emit

[`control-plane-project-charter` §10](../../SKILL.md#10-language-dispatch) states the dispatch rule.

---

**The slugs the CLI accepts** — do not invent one; the flag is validated and rejects it:

| Command | Accepted `--language` |
|---|---|
| `up function generate` | `go`, `go-templating`, `kcl`, `python` |
| `up test generate` | `go`, `go-templating`, `kcl`, `python`, `yaml` |
| `up project init` | `go`, `go-templating`, `kcl`, `python` (and the same set for `--test-language`) |

Never scaffold a **function or test directory** by hand. `up function generate` and
`up test generate` produce the layout the CLI expects — `pyproject.toml` pins, the models
path, the pipeline step in the composition — and the layout differs between a
template-initialised project and a generated one; match what the project already uses. That
includes a stub function to make an early build pass: a project builds with no function at
all, and its first build has to run before `up function generate`
(author-configuration-package, Phases 6–7).

The XRD is the exception (§5): nothing wires it up, and `up project build` reads whatever is in
`apis/`.

### What the generators actually emit

| Command | What you get |
|---|---|
| `up project init --template <t> --language <l>` | whatever Crossplane generation the template holds, and they differ. The cloud templates (`project-template-aws-s3`, `-azure-storage`, `-gcp-storage`) are **v1**: XRD at `apiextensions.crossplane.io/v1` with `claimNames` and no `scope`, functions importing the **non-`.m.`** provider models, `kind: ProviderConfig` in their E2E tests. `project-template-k8s-webapp` is **v2**: `apiextensions.crossplane.io/v2`, `scope: Namespaced`. `--scratch` has no XRD at all. These are the five templates up v0.55.0's wizard offers, as their default branches stood on 2026-10-08. The template's name proves nothing, and a template can change without a new `up`, so **check the XRDs' `apiVersion`** (`grep -h '^apiVersion' apis/*/definition.yaml`): `…/v1` is a v1 project, `…/v2` a v2 one. Do that before applying §5: its rules are for v2 and break a v1 project. |
| `up test generate <n>` | `tests/test-<n>/` — the CLI prepends `test-` itself. Passing `test-<n>` gives you `tests/test-test-<n>/`. The stub does not run: `assertResources: []` plus empty `xrPath`, `compositionPath` and `xrdPath`, and the empty `compositionPath` fails before any assertion with `cannot load Composition from "": not a composition: /`. That is a broken test, not RED (§3): fill the paths in first. |
| `up composition generate <xrd>` | one step per Function in `dependsOn` (input stubbed from its input CRD, if any), auto-ready last. It adds a `crossplane-contrib-function-auto-ready` step and `crossplane-contrib/function-auto-ready` at `'>=v0.0.0'` to `dependsOn`, even when the project already declares an auto-ready function (`upbound/function-auto-ready`), which then gets a step of its own as well (observed with up v0.55.0). Only an existing `xpkg.upbound.io/crossplane-contrib/function-auto-ready` entry stops it: then no dependency is added and its constraint stays (source). When the project declares its own function set, delete the duplicate step and its dependency, and say so in your report. Your function is not wired in; a test pointed at it renders nothing and passes vacuously. `up function generate <n> <composition-path> --language <l>` inserts the step. |
| `up xrd generate <example>` | a schema inferred from one example: no `required:`, no `default:`, no `minItems`, `status` properties only from the example's own `status`, `integer` widened to `number`, an open-ended map frozen into the keys the example used, and an array's object items as the union of the elements' keys (§5). |

The `functionRef` name in a composition is `<repository-org>-<repository-name><function-dir>`
(no separator between the repository name and the directory), taken from `spec.repository` in
`upbound.yaml` when you generate. **Set the project metadata before
`up composition generate` and `up function generate`:** the embedded function's name follows
`spec.repository`, so changing it afterwards leaves every `functionRef` naming the old function,
and they must be regenerated or rewritten with this formula.

A `functionRef.name` that departs from the formula names no function the render knows: every
render fails with `unknown function`, the same error as an external function missing from
`dependsOn`. Keep the generated name; don't hand-edit it or take one from anywhere else over the
formula.

`up function generate <n> <composition-path>` on an existing `functions/<n>` asks whether to
overwrite it. Without a TTY it prints `operation cancelled by user` and exits 1 (observed with
up v0.55.0). To wire a function that already exists, add the step by hand instead: a
`functionRef.name` from the formula above and `step: <n>`, before the auto-ready step.

None of the six generators (`function`, `test`, `xrd`, `composition`, `example` and `operation
generate`) has `--force` or `--yes`. On an existing target, each one prompts and, without a TTY,
exits 1 the same way, so don't search for a flag. `echo y |` works only with `TERM=dumb`, and it
merges into the target instead of replacing it. To regenerate, remove the target first (only if
nothing in it is worth keeping), or edit it by hand.
