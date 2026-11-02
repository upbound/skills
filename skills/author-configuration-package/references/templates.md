# Templates: files, questions and reports for a configuration package

The files this skill writes by hand, the questions to ask when the spec does not answer them,
what to check when a build fails, and the hand-off report. The order of the work is SKILL.md's
phases; function and test syntax is under `control-plane-project-charter/references/languages/`.

- [Templates](#templates)
- [Questions for a new project](#questions-for-a-new-project)
- [XRD field wizard](#xrd-field-wizard)
- [When a build fails, or the XR never gets Ready](#when-a-build-fails-or-the-xr-never-gets-ready)
- [Hand-off report](#hand-off-report)

---

## Templates

The XRD has no template here: write it from the v2 skeleton in
`control-plane-project-charter/references/charter/v2-resources.md` (SKILL.md Phase 3).

### upbound.yaml

Cap the major of every dependency: a bare `up dep add <ref>` writes `'>=v0.0.0'`. Providers join
`dependsOn` in Phase 4. Neither note is a YAML comment below, because the first build strips
comments from `upbound.yaml` (SKILL.md, Phase 4).

```yaml
apiVersion: meta.dev.upbound.io/v2alpha1
kind: Project
metadata:
  name: {project-name}
spec:
  dependsOn:
    - apiVersion: pkg.crossplane.io/v1
      kind: Function
      package: xpkg.upbound.io/crossplane-contrib/function-auto-ready
      version: '>=v0.2.1, <v1.0.0'
  description: {description}
  license: Apache-2.0
  maintainer: {maintainer}
  readme: |
    Crossplane configuration package for {project-name}
  repository: xpkg.upbound.io/{org}/{project-name}
  source: github.com/{org}/{project-name}
```

### Provider dependency

```yaml
- apiVersion: pkg.crossplane.io/v1
  kind: Provider
  package: xpkg.upbound.io/upbound/provider-aws-ec2
  version: '>=v2.0.0, <v3.0.0'
```

### .gitignore

```text
# Build artifacts
_output/
*.uppkg

# Generated models
.up/

# Go: `go build ./...` writes a binary named after its directory. One line per
# function; the test patterns cover every scaffolded test directory.
functions/<function-name>/<function-name>
tests/*/test-*
tests/*/e2etest-*

# IDE files
.vscode/
.idea/
*.swp
*.swo
*~

# OS files
.DS_Store
Thumbs.db

# Dependency cache
.cache/
.venv/
```

### Example XRs

Under `examples/<kind-lowercase>/<xr-name>.yaml`, where `up example generate` writes them.
The minimal one sets only the required fields:

```yaml
# examples/{kind-lowercase}/{xr-name}.yaml
apiVersion: {group}/{version}
kind: {Kind}
metadata:
  name: {xr-name}
  namespace: default
spec:
  region: us-west-2
```

The complete one sets every field, required and optional:

```yaml
# examples/{kind-lowercase}/{xr-name}-complete.yaml
apiVersion: {group}/{version}
kind: {Kind}
metadata:
  name: {xr-name}-complete
  namespace: default
spec:
  region: us-west-2
  cidrBlock: "10.0.0.0/16"
  enableDnsHostnames: true
  tags:
    environment: development
```

---

## Questions for a new project

Only for what the spec does not say (SKILL.md Phase 1).

| Field | Example | Notes |
|-------|---------|-------|
| Project name | configuration-aws-database | prefix with `configuration-` |
| API group | platform.acme.io | domain format |
| Cloud provider | AWS, Azure, GCP, other | for the provider packages |
| Organization | acme | the `repository` field |
| Maintainer | `Platform Team <platform@acme.io>` | |
| Function language | kcl, python, go, go-templating | the `--language` of Phase 7; tests follow it (charter §10) |

Then the resource:

| Field | Example | Default |
|-------|---------|---------|
| Resource Kind | VPC, Database | required |
| Plural name | vpcs, databases | from the Kind |
| Version | v1alpha1 | `v1alpha1` (`control-plane-project-charter/references/charter/xrd-design.md`) |

In an existing project, ask instead whether to add a resource or change an existing one.

---

## XRD field wizard

Only when there is no spec to read the fields from. You still write the XRD by hand; the
wizard collects its fields. Ask in a loop until the user says done, and write the OpenAPIv3
schema into `apis/<plural>/definition.yaml` as you go:

```text
WHILE user wants to add fields:
  1. Ask field name
  2. Ask field type (string/integer/boolean/array/object)
  3. Ask description
  4. Ask if required
  5. Ask default value (optional)
  6. Ask "Add another field?"
END LOOP
```

```yaml
properties:
  {fieldName}:
    type: {fieldType}
    description: "{description}"
    default: {defaultValue}  # only if provided
required:
  - {requiredField}
```

**Add reasonable validation, but keep the draft valid.** Accurate types, `required`,
descriptions, a CIDR `pattern`, well-scoped enums and defaults are welcome, as long as every
constraint still **accepts the values in the user's XR draft**: a lowercase `location` enum
that accepts only `westeurope` rejects the draft's `West Europe`. If a reasonable constraint
conflicts with a draft value, normalize the value or relax the constraint, or ask.

---

## When a build fails, or the XR never gets Ready

| Symptom | Check |
|---|---|
| The model tree (SKILL.md Phase 6) has no `.m.` models after the first build | the provider is v1.x (the `.m.` groups ship from v2.0.0); the package name is wrong |
| `up function generate` errors about missing models | the first build did not run or failed: build, check the model tree, then generate |
| the first build fails | `upbound.yaml` syntax, provider versions, then the XRD's syntax |
| the final build fails | the function's own sources (Go compiles here; KCL and Python are not type-checked, charter §8), its module or dependency file, and the composition's pipeline |
| the XR never reaches Ready | `crossplane-contrib-function-auto-ready` is not the last step in the pipeline: move your function's step before it |

A composition test passing locally while the control plane rejects the composition on
`spec.mode` is `mode: Resources` (SKILL.md Phase 5).

---

## Hand-off report

After the final build, report what ran and what it printed, not a checklist
(`control-plane-project-charter` §4):

```markdown
## Package scaffolding: {project-name}

**Resource:** {Kind} ({api-group}/{version}) · **Language:** {language}

**Ran:**
- `up project build` → exit {code}; package {path under _output/}
- `check_xrd_schema.py apis/*/definition.yaml` → exit {code}; {findings, or none}

**Layer reached:** package build. Nothing rendered, no tests run, nothing deployed.
**Assumed / not verified:** {e.g. Kinds confirmed from the generated models; ProviderConfig not applied}

### Next steps
1. Tests and composition logic, test first: `author-tests` writes the failing test,
   `author-composition` makes it pass (`functions/{name}/`)
2. Gate: the project's own gate if it has one, else `verify-configuration`
```
