# Composition patterns — what they mean

**Open these first, if they are not open in this session:** the `control-plane-project-charter`
skill, and your language's index and function file in
`control-plane-project-charter/references/languages/` (Go: `go.md`, `go/functions.md`; Python: `python.md`, `python/patterns.md`; KCL: `kcl.md`,
`kcl/patterns.md`; go-templating and YAML: their one file). This file says
what a pattern means; those say how to write it.

- [The object model every language builds](#the-object-model-every-language-builds)
- [Pattern: module organisation](#pattern-module-organisation)
- [Pattern: the configuration object](#pattern-the-configuration-object)
- [Pattern: the guard-clause chain — the failure composition tests cannot see](#pattern-the-guard-clause-chain--the-failure-composition-tests-cannot-see)
- [Pattern: conditional creation, and the `ready OR exists` rule](#pattern-conditional-creation-and-the-ready-or-exists-rule)
- [Pattern: references beat status plumbing](#pattern-references-beat-status-plumbing)
- [Pattern: list fields — one resource per element is a decision](#pattern-list-fields--one-resource-per-element-is-a-decision)
- [Namespaces, connection details, ProviderConfig readiness](#namespaces-connection-details-providerconfig-readiness)
- [Pattern: flexible maps](#pattern-flexible-maps)
- [Pattern: merging](#pattern-merging)
- [Naming](#naming)
- [A green test with a misbehaving resource](#a-green-test-with-a-misbehaving-resource)
- [Migrating a function to v2](#migrating-a-function-to-v2)

The syntax is in the charter's language files, indexed by
`control-plane-project-charter/references/languages/README.md`, under the same pattern names.

---

## The object model every language builds

A composition function receives a `RunFunctionRequest` and returns a `RunFunctionResponse`.
Three parts matter, identical in every language:

| Part | What it is | The mistake it invites |
|---|---|---|
| `req.observed.composite` | the XR as it currently exists, including `status` | reading it as a plain map when the language gives you a typed object, or vice versa |
| `req.observed.resources` | composed resources **that already exist**, keyed by composition key | assuming it is populated. In a composition test it is `{}` unless the test supplies `observedResources`, with mocks as `control-plane-project-charter/references/charter/evidence.md` (Coverage) describes |
| `rsp.desired.resources["key"]` | what you want to exist, keyed by composition key | treating the key as cosmetic. It becomes `crossplane.io/composition-resource-name`, and Crossplane derives the resource name from it |

**The composition key is an API.** A composed resource the function stops returning, because
its key was renamed or the resource removed, is deleted by Crossplane on every existing XR that
runs the new version, and under the default management policies its cloud resource with it; a
renamed key then creates a new one. Either is a migration: to keep the cloud resource, first
ship a version that returns it with `Delete` dropped from its `managementPolicies`
(`control-plane-project-charter/references/charter/v2-resources.md`), let every XR run it,
then stop returning it. Choose keys as deliberately as a field name.

---

## Pattern: module organisation

**One module per resource domain**, with the entry point doing orchestration only — imports,
parameter extraction, the config object, and calls into the modules. A single flat function
accumulates guard clauses (below), and the guard chain is the failure composition tests
cannot see; splitting by domain keeps each conditional local to the resources it governs.

A single-file function is fine for a simple composition. If you can name the domains, split.

---

## Pattern: the configuration object

Extract the XR's parameters **once**, into a single object, and pass that to every module.
If each module reads the XR itself, a schema change touches every module and a defaulted
field gets defaulted differently in two places.

Include the core parameters, the feature flags, the lists, and the merged tags. Apply
defaults there, so there is exactly one answer to "what does this field mean when the user
omits it".

---

## Pattern: the guard-clause chain — the failure composition tests cannot see

Template functions are written as a sequence of early returns:

```
if the bucket is not observed yet:        return
if it has no external name yet:           return
if versioning is disabled:                return
```

**Anything appended after those inherits every one of them.** A resource added at the end of
the function silently disappears whenever `versioning: false`, and the test that renders with
versioning enabled passes.

**Give each optional resource its own conditional block** rather than another early return,
and place it above unrelated guards. When you add to an existing function, read the returns
above your insertion point before you write anything.

The matching test: one per input shape, including a **minimal XR that omits every optional
field**, which catches an unintended guard.

---

## Pattern: conditional creation, and the `ready OR exists` rule

A resource created only when some other resource is ready must **also** be kept when it
already exists:

```
if dependency_is_ready OR resource_already_exists:
    create it
```

Testing only `dependency_is_ready` deletes the resource whenever the dependency briefly goes
un-ready — a cluster restart takes the Helm release with it.

---

## Pattern: references beat status plumbing

When resource B needs an ARN, ID, or name produced by resource A:

| Approach | Cost |
|---|---|
| **`*Ref` / `*Selector` field** — the provider resolves it | single-pass composition, no readiness branch; assert the ref or selector |
| Read A's `status` and write it into B | a second reconcile, and a readiness branch only a test with `observedResources` reaches |

**Not inside a list.** A `*Ref` or `*Selector` in a `forProvider` list without
`x-kubernetes-list-type: map` never settles: the provider's forced server-side apply of the
resolved value takes the whole list, and Crossplane's next apply takes it back
(crossplane-runtime `pkg/reconciler/managed/api.go`). No render shows it. Read the target's ID
from its observed status instead.

**Check for a `*Ref` before writing any status-plumbing logic.** The generated schema lists
them. A resource that consumes another one you also create needs only
`<field>Ref: {name: <target-name>}`, the `metadata.name` your function sets on the target
(charter §5) — no status reading at all.

Selectors come in three shapes, and the choice is about coupling:

| Selector | Matches | Use when |
|---|---|---|
| direct `*Ref` by name | the exact resource you named | you set the target's `metadata.name` yourself (charter §5), not a composition key |
| `matchControllerRef` | resources composed by the same XR | you want "the VPC belonging to this XR" without naming it |
| `matchLabels` | anything carrying the labels | crossing composition boundaries — the loosest coupling, and the easiest to break silently |

---

## Pattern: list fields — one resource per element is a decision

An XR field that is a list does **not** imply N resources. The mistake renders perfectly and
fails only at the provider. Before writing the loop, answer three questions about the cloud
API:

1. **Are the elements independent?** Or can two of them conflict — overlapping prefixes,
   overlapping CIDR ranges, duplicate keys?
2. **Does the API want one aggregate object holding N entries**, rather than N objects? S3
   lifecycle does: one `BucketLifecycleConfiguration` holding N rules.
3. **Is there an account- or region-scoped limit** that N elements would breach?

`control-plane-project-charter/references/charter/provider-schema.md` has the rule classes and
where they are written down. If the models cannot answer, say which API-level rule you could
not confirm rather than assuming independence.

Upjet gives some list fields misleadingly **singular** names — `attribute`,
`globalSecondaryIndex`. Read the generated type, not the field name.

---

## Namespaces, connection details, ProviderConfig readiness

- **Namespaces:** omit `metadata.namespace` on everything a namespaced XR composes, child XRs
  and Secrets included (charter §5).
- **Connection details:** a v2 XR publishes none (no `writeConnectionSecretsToNamespace`), so
  compose the Secret yourself from the observed resources' details, read by composition key.
  When they arrive, and what a render shows: charter §5 and
  `control-plane-project-charter/references/charter/v2-resources.md`.
- **A composed ProviderConfig**, or anything else `function-auto-ready` cannot judge: mark it
  ready explicitly, or the XR never becomes ready.

---

## Pattern: flexible maps

Tags, labels and annotations are user-supplied key-value maps. Declare them in the XRD with
`additionalProperties: {type: string}`. With fixed `properties`, which a schema inferred from an
example always has, every key the user did not supply materialises as a null that typed
languages reject at parse time. Convert the value to the language's plain map before
assigning it.

**Label values must also be Kubernetes-legal** — no `/` or `:`, max 63 characters. Sanitize
user-supplied tags before using them as labels.

---

## Pattern: merging

Where a language offers a merge (KCL's `|`, a spread, a dict update), **the later operand
wins**: defaults first, specifics last.

Some "update" operations replace at the nested level, so two writes to `status` leave only
the second: write one call with all the keys (the language file).

---

## Naming

`{type}-{resourceName}-{qualifier}` — e.g. `subnet-web-public-a`. Predictable keys make
`render.log`, which you debug against, readable. Keep them stable: a rename is a migration
(top of this file).

---

## A green test with a misbehaving resource

**When a test passes but the resource misbehaves on a control plane:**
1. Read the render (`control-plane-project-charter/references/charter/evidence.md`) — the test
   may never have asserted the resource.
2. Look for a `providerConfigRef` whose `kind` and name match no object that exists; the
   symptoms are in `control-plane-project-charter/references/charter/v2-resources.md`.
3. Check the guard-clause chain and readiness branches; neither is exercised locally.
4. Generation climbs, or the XR reports `WatchCircuitOpen`: a reference inside a list
   ([above](#pattern-references-beat-status-plumbing)).

Language-specific error messages — Pydantic validation, KCL type errors, TypeScript
compilation — are in the matching `languages/` file.

---

## Migrating a function to v2

The language-neutral v1→v2 changes are in `plan-v2-migration`'s `breaking-changes.md`
reference; the spelling per language is in `languages/`. Two points belong to the function itself:

- Add the language's XR-parsing bootstrap where it is required (the language file says
  whether).
- Never rename a function to add a language suffix: the function name is the published
  registry path.
