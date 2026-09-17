# Provider Conformance Requirements

These are the requirements a Crossplane provider must meet to be accepted into the ecosystem. They apply to every provider regardless of who authors it (internal engineers, external contributors, community authors, partners, or agents) and regardless of the engine, language, or tooling used to build it. A provider is conformant when it satisfies every rule below and any deviation is declared under TST-4.

Each rule is stated as a technical rationale followed by a table of accepted values with a conformant and a non-conformant example.

## Schema and API design

### SCH-1 — Consistent naming

A provider's field and type names are a public API surface that users read, compose against, and build tooling on top of, so they must follow one shared naming convention across the entire ecosystem rather than inheriting whatever casing the underlying API or source schema used. This covers the mechanical transform from the source's naming, often snake_case, into the Kubernetes convention of lowerCamelCase fields and PascalCase types, and, critically, a shared treatment of acronyms so that initialisms are cased identically everywhere: IPv6, TLS, ARN, ID, and URL resolve to one canonical form rather than being title-cased ad hoc. This is a conformance rule and not a style preference because inconsistency compounds across a large ecosystem: a user who learns that one provider spells a field `ipv6CidrBlock` should not have to discover that another spells the same concept `iPv6CIDRBlock`, and cross-provider tooling that keys on field names breaks when the same concept is spelled differently. Names are derived deterministically from the underlying API so the mapping is predictable and reviewable rather than chosen per field.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Shared casing convention with a canonical acronym set (IPv6, TLS, ARN, ID, URL); lowerCamelCase fields, PascalCase types | An IPv6 CIDR field is `ipv6CidrBlock` in every provider | The same concept is `iPv6CIDRBlock` in one provider and `ipV6Cidr` in another |

### SCH-2 — Separated spec

A managed resource's schema must separate three distinct concerns: the user's desired configuration, values meaningful only at creation time, and the state observed back from the external system. Desired configuration is authoritative and continuously reconciled toward; creation-only values seed the resource but are not enforced afterward, so a value the system computes or mutates post-creation does not cause perpetual diffs; observed state is read-only status reflecting what actually exists. Collapsing these blurs the boundary between intent and reality, and the failure is concrete: if a cloud-assigned value such as an allocated address or generated identifier lands in the desired-configuration block, the provider reads it as user intent, compares it against the empty value the user actually set, detects a diff on every pass, and either fights the system by trying to unset it or churns the object forever. Keeping the three apart is what lets a resource be both declaratively managed and safely observed.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Three distinct sections: desired configuration; creation-only initialization; observed state | A cloud-assigned address appears only in observed state and never diffs | The address is placed in desired configuration, so the provider perpetually detects drift against it |

### SCH-3 — Policy-aware requiredness

Whether a field is required must depend on the management policy, because the same field can be mandatory in one mode and meaningless in another. A field needed to create a resource is genuinely required only when the provider will create or update; when the resource is being observed or imported, the user has not supplied and should not have to supply create-time inputs, so enforcing the field as unconditionally required rejects legitimate observe-only and import objects at admission before the controller ever runs. The requirement must also be satisfiable from either the desired configuration or the creation-only values, since a field can legitimately be provided through either path. This is expressed as a conditional validation on the type that predicates the requirement on the management policy rather than a static required marker. The failure is silent and admission-time: a user adopting an existing database to watch it under observe-only supplies none of the create parameters, and a rigidly required field turns that valid intent into a rejected apply.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Required only when the policy includes create or update; satisfiable from desired configuration or creation-only values | Importing an existing resource under observe-only succeeds with no create-time fields set | An unconditional required constraint rejects an observe-only import at admission |

### SCH-4 — Declared validation

Input constraints, enumerations, formats, numeric ranges, immutability, and defaults, must be declared on the API type itself rather than enforced only in controller logic, so the API server rejects invalid input at admission and composition can reason about the schema statically. Declared validation runs before an object is ever persisted, which turns a typo into an immediate, actionable admission error at the point of apply instead of a reconcile failure discovered minutes later after a round trip to the external system. It also makes the contract visible: composition functions, editor tooling, and generated documentation all read the declared constraints, whereas validation buried in a controller is invisible to everything except the controller. Immutability in particular must be declared so the API server rejects a mutation to an immutable field rather than the provider discovering it mid-reconcile and having to reconcile an impossible state.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Enums, formats, ranges, immutability, and defaults declared on the type | `storageClass: SUPERCOLD` is rejected at apply time by a declared enum | An invalid value is admitted and only fails later during reconcile |

### SCH-5 — Consistent presentation

Every resource must present itself through the same standard surfaces so one set of tooling and one operator mental model work uniformly across all providers. Concretely this means a status subresource, so spec and status have independent write paths and a status update does not bump the object's generation; a consistent set of printer columns surfacing at minimum sync state, readiness, the external name, and age; and membership in the standard categories so broad selectors resolve resources uniformly. The consequence of skipping this is not merely cosmetic: an operator scanning a mixed fleet with a single command relies on the same columns meaning the same thing on every resource, and dashboards and scripts that select by category silently miss resources that omit it. Consistent presentation is what makes a heterogeneous set of providers legible as one platform.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Status subresource; printer columns for sync, readiness, external name, age; standard categories | Listing any resource from any provider shows the same sync, readiness, external-name, and age columns | A resource omits the readiness column or is missing from the standard categories |

### SCH-6 — Stable grouping

APIs must be organized one service per group under a stable domain, and a resource's group and kind are part of its permanent identity that must never change after release. The group and kind together form the fully qualified type that every stored object, composition, and reference is bound to; changing either is indistinguishable from deleting the old type and introducing a new one, which orphans every object a user has already applied and every composition that references it. Namespaced variants live under a parallel domain that marks them as namespaced, so the cluster-scoped and namespaced forms of a service are distinguishable but clearly related. Choosing the domain once and holding it stable is a durability requirement: it is the anchor that lets objects, references, and conversions remain valid across the entire supported life of the provider.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Group form `<service>.<provider>.<domain>` (e.g. `ec2.aws.crossplane.io`); namespaced variants under a parallel domain; unchanged after release | An EC2 instance remains in `ec2.aws.crossplane.io` across every release | A later release moves it to `compute.aws.crossplane.io`, orphaning existing objects |

### SCH-7 — Deliberate scope

Each resource must be offered at a deliberately chosen scope, cluster-scoped or namespaced, and where both are offered they must be at full parity. Scope is not a cosmetic property: namespaced resources participate in namespace-based tenancy and RBAC, can be isolated per team or tenant, and reference secrets and other resources within their namespace, while cluster-scoped resources are global. Because the ecosystem is migrating toward namespaced resources for multi-tenancy, a service that offers both must present the identical kind, schema, and behavior in each, differing only in scope and group domain, so a team adopting namespaced resources for isolation is not silently handed a reduced or divergent API. A parity gap means the choice of scope becomes a choice of feature set, which is exactly the coupling this rule prevents.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Cluster or namespaced, chosen deliberately; where both are offered, identical kind, schema, and behavior | The namespaced variant of a resource exposes the same schema as its cluster-scoped form | The namespaced variant omits fields present in the cluster-scoped form |

## Runtime behavior

### RT-1 — External name

Every managed resource must be linked to its external resource by a stable external name that is established at creation and is sufficient on its own to rediscover the external resource later, even after the provider has lost all local state. The external name is the durable identity of the resource; it is recorded on the managed object and is the only thing the provider can rely on to find the real resource on a subsequent reconcile, after a restart, or during import and disaster recovery when there is no cached state at all. How the name maps to the external system varies: some resources are named directly by the user, some receive a provider-assigned identifier that must be captured at creation, some require a composite assembled from several fields, and the identifier used to import an existing resource sometimes differs from the one stored afterward, and both forms must be handled. This is the single most consequential runtime property, because an external name that is wrong, unstable, or not captured at creation causes the provider to leak the real resource (losing track of something still billing), adopt the wrong resource, or create a duplicate on the next reconcile.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| User-provided name; provider-assigned identifier; templated composite; parameter-derived. Import identifier may differ from the stored identifier | After local state is wiped, the provider re-adopts the same external resource from its external name alone | On restart the provider creates a duplicate because it keyed on a local handle it no longer has |

### RT-2 — Crash-safe create

Creation spans two operations that cannot be made atomic: the external resource is created in the remote system, and then its identity is recorded on the managed object. A crash, restart, or lost response in the window between them leaves the provider unsure whether the external resource exists, and this ambiguity must be handled safely rather than resolved by assumption. A conformant provider records that a create is pending before it issues the create call and confirms or clears that marker only after the external name has been durably written back, so on the next reconcile it can detect that a create may already be in flight and reconcile against the possibly-existing resource instead of blindly issuing a second create. Nothing computed during create other than the recorded identity can be relied on to survive, because the reconcile that follows a crash starts fresh. Getting this wrong duplicates or orphans real, often billable, infrastructure under precisely the partial-failure conditions that occur constantly at scale.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A create is marked pending before it is issued and confirmed or cleared only after identity is durably recorded; an ambiguous retry surfaces the ambiguity rather than re-creating | A create interrupted before its identity is recorded is detected on retry and not repeated | A crash mid-create leads the next reconcile to issue a second create, duplicating a billable resource |

### RT-3 — Read-only observation

Observation must be a pure read of the external system: it inspects the external resource and reports what it found, and it must never mutate that resource as a side effect. The reconcile loop depends on observation returning an accurate picture, at minimum whether the resource exists, whether it matches desired state, its connection details, and whether observation itself late-initialized any spec fields, so the loop can decide correctly whether to create, update, or do nothing. An observation that writes to the external system violates the separation between the read and write phases and can cause the provider to act on state it just changed; an observation that misreports up-to-dateness is equally damaging in the other direction, either reporting a false diff that triggers a needless update every pass, or reporting false convergence that hides real drift the user is relying on the provider to correct.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Observation performs no external writes; it reports existence, up-to-dateness, connection details, and whether it changed the spec | Observing an up-to-date resource reports up-to-date and triggers no update | Observation edits the external resource, or reports drift on a resource that has not changed |

### RT-4 — Bounded late-initialization

A provider may late-initialize, that is, back-fill spec fields the user left unset with values the external system chose, but only when doing so actually changes the spec, and never on subsequent passes once the fields are populated. Late-initialization is how a server-assigned default becomes visible in the spec, but because the runtime persists spec changes ahead of status, a provider that reports having late-initialized on every observation forces a spec write every reconcile, which loses queued status updates and drives the object into a perpetual reconcile loop. The behavior is therefore bounded: back-fill unset fields exactly once, report a change only when the spec truly changed, and never overwrite a value the user explicitly set, since that would silently override user intent. This failure is invisible in a quick test and only manifests under sustained reconciliation, which is what makes stating it as a rule necessary.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Unset fields back-filled once; a change reported only when the spec actually changes; user-set values never overwritten | A server-assigned default is recorded once and then left untouched | The object is rewritten on every observation, spinning the reconcile loop |

### RT-5 — Management policies

The management policy is a per-resource declaration of which reconcile actions the provider is permitted to take: observe, create, update, delete, and late-initialize, in any combination. It is evaluated on every reconcile pass, before the provider acts, and each action must be gated behind its corresponding permission rather than assumed. The loop's normal flow, observe the external resource, compare to desired state, then create, update, or delete to converge, must be short-circuited according to the policy: under observe-only the loop runs through observation and stops, publishing status and connection details without ever entering the write path; under an immutable policy the update path is disabled so a detected diff never triggers a mutation; under a no-delete policy the external resource is left intact when the managed resource is removed, and only the Kubernetes object and its finalizer are cleaned up. A provider that hardcodes full reconciliation ignores this gating entirely, so the failure is not a missing feature but active harm: a user who set observe-only on a production database to inspect it safely gets writes anyway, and a user who set no-delete to protect data loses it when the object is removed.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| `FullReconcile`, `ObserveOnly`, `Import`, `Immutable` (no update), `RetainOnDelete` (no delete), `Pause` | Under `ObserveOnly`, the loop observes and publishes status but never enters create, update, or delete | Issues an update when a diff is found on a resource marked `ObserveOnly` |

### RT-6 — Not-found

A provider must cleanly distinguish "the external resource does not exist" from "an error occurred while trying to observe it," because the reconcile loop takes opposite actions in each case. A genuine not-found during normal reconciliation means the resource should be created; a not-found during deletion means the delete is complete and the finalizer can be removed; an error, by contrast, means the current state is unknown and the provider must retry without drawing any conclusion. Conflating the two is a common and damaging defect: if absence is misreported as an error, deletion never completes and the object hangs with its finalizer forever; if an error is misreported as absence, the provider concludes a still-existing resource is gone and recreates it, duplicating infrastructure. External systems signal absence inconsistently, sometimes as a typed not-found and sometimes as an error payload that must be inspected, so the provider must interpret those signals deliberately rather than treating any failure as absence.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Absence maps to not-found; a failure maps to a retryable error; the two are never conflated | A resource deleted out-of-band is reported not-found so the managed object finalizes cleanly | Absence is surfaced as an error, so deletion hangs indefinitely |

### RT-7 — Secret handling

Sensitive values a provider handles, generated passwords, tokens, keys, connection strings, must be published only as connection-secret details and must never be written into the managed resource's spec or status. The connection secret is the surface designed to carry this data under Kubernetes secret access controls; the managed object is not, and is typically readable by a much broader audience through get and list access at that scope. A sensitive value mirrored into status is therefore effectively exposed to every operator and controller watching the resource, defeating the purpose of treating it as a secret. The provider must map sensitive observed or generated fields into the connection secret at the point it encounters them and keep them out of the resource surface end to end.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Sensitive values confined to the connection secret; absent from spec and status | A generated database password is written only to the connection secret | The password is exposed in the resource's status |

### RT-8 — Asynchronous operations

Operations that can take longer than a reconcile should, provisioning a cluster, a database, or any resource with a multi-minute lifecycle, must be handled asynchronously: the provider issues or checks the operation, records progress, and returns, polling across successive reconciles within declared per-operation timeouts rather than blocking the worker until the operation finishes. Controller workers are a shared, finite pool; a reconcile that blocks for the ten minutes a managed cluster takes to come up holds its worker for that entire time and starves every other resource queued behind it, converting one slow resource into fleet-wide latency. Declaring explicit timeouts per operation also bounds how long the provider will wait before treating an operation as failed, so a stuck create does not wait forever. The asynchronous pattern keeps the loop responsive regardless of how slow the underlying system is.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Long operations poll across reconciles within declared per-operation timeouts (create, read, update, delete) and do not block the worker | A ten-minute provision is polled across reconciles, leaving the worker free | The worker blocks for the full provision, stalling other resources |

## ProviderConfig and credentials

### PC-1 — Standard configuration

Every provider must expose its configuration through a provider configuration API whose shape is consistent with the rest of the ecosystem, because provider configuration is the first thing every user touches and the point where cross-provider consistency is most visible. A user who has configured one provider, selecting a credential source, pointing at a set of credentials, setting endpoints or provider-wide options, should be able to configure the next by analogy rather than learning a new model. Consistency here also lets shared tooling, examples, and platform abstractions treat provider configuration uniformly. A bespoke configuration model unique to one provider forces every user and every tool to special-case it.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A provider configuration API matching the ecosystem's standard shape | A user configures a new provider by analogy with providers they already use | The provider invents a configuration model unlike any other provider's |

### PC-2 — Standard credential sources

A provider must support the standard set of credential sources so the same provider can authenticate the same way across the environments a user actually runs in. At minimum this means a referenced Kubernetes secret, a filesystem source, an environment source, and injected platform identity such as workload identity or an equivalent instance-identity mechanism, since these correspond to how credentials are supplied in development, in CI, and in production. Injected identity in particular matters because it avoids long-lived static credentials entirely, which is the posture regulated and security-conscious deployments require. Supporting only an idiosyncratic subset forces users into per-provider workarounds, for example mounting a static secret in production because the provider cannot consume the platform identity everything else uses.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Referenced secret; filesystem; environment; injected platform identity (e.g. workload identity) | The same provider uses a mounted secret in development and workload identity in production, with no code change | The provider supports only a referenced secret, forcing static credentials in production |

### PC-3 — In-use protection

A provider configuration that is still referenced by live managed resources must not be deletable out from under them, and its in-use state must be observable. Managed resources depend on their provider configuration to authenticate every reconcile; if the configuration is deleted while resources still reference it, those resources can no longer be reconciled or cleanly deleted, stranding real infrastructure with no management path. The provider enforces this by tracking usage and holding a finalizer on the configuration so a deletion request is blocked while any resource references it, and by surfacing that the configuration is in use so an operator understands why the delete is pending. This mirrors the in-use protection Kubernetes applies elsewhere and exists to prevent an accidental configuration deletion from cascading into unmanageable resources.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Deletion blocked while referenced; in-use state surfaced on the configuration | Deleting a configuration that live resources reference is blocked and reports that it is in use | The configuration deletes immediately, stranding the resources that depended on it |

## API evolution, storage, and migration

### EVO-1 — Version stability tiers

Not every version carries the same stability promise, and conflating them either over-constrains iteration or under-protects users. Following Kubernetes API conventions, a version's maturity is encoded in its name and must match its guarantees. A `v1alpha1` version is explicitly unstable: it may change incompatibly or be removed from one release to the next with a notice but no long window, which makes it the sanctioned place to iterate on a new API before committing to its shape. A `v1beta1` or later version is stable: it is frozen against breaking changes and subject to the full evolution and deprecation discipline in the rules below. Marking a version alpha is a promise that it is unstable; marking it beta is a promise that it is not. Choosing maturity deliberately channels churn into alpha rather than forcing it onto a version users were told to depend on.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| `v1alpha1`: unstable, may change or be removed with notice. `v1beta1`+ and `v1`: stable, frozen, full evolution rules apply | An experimental field is iterated in `v1alpha1`, then stabilized into `v1beta1` once its shape is settled | A breaking change is made to a served `v1beta1`, or an alpha version is treated as permanent |

### EVO-2 — No in-place breakage of stable versions

Once a stable version (`v1beta1` or later) is served, its schema is frozen against breaking changes for the life of that version. No field may be renamed, removed, retyped, or made newly required, and no default may change in a way that reinterprets objects already stored, because each such change breaks objects users have applied and compositions written against that version. Only strictly additive, optional changes are permitted in place, since those neither invalidate nor reinterpret any existing object. This is the Kubernetes stability contract applied to providers: a served stable version is a promise that an object valid yesterday remains valid and unchanged in meaning tomorrow.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Additive-only within a served stable version (new optional fields) | A new optional field is added to `v1beta1` | A field is renamed, removed, retyped, or made newly required in a served `v1beta1` |

### EVO-3 — Breaking changes go to a new version

When a change would break a served stable version, it is delivered as a new version rather than applied in place. The new version differs in schema, every prior version remains served, and objects flow between them by conversion, so users are carried forward automatically and never have to rewrite objects they have already applied. Structural changes are handled this way: reshaping a nested single-element list into an embedded object, for example, is introduced as a new version while the prior version stays served and converted. Introducing a version is the mechanism that makes the freeze in EVO-2 livable rather than paralyzing.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A breaking change ships as a new version; all prior versions remain served with conversion | A list-to-object reshape ships as `v1beta2` with `v1beta1` still served | The reshape edits `v1beta1` in place |

### EVO-4 — Conversion completeness and strategy

A multi-version resource must be able to convert between all served versions, and it must do so through a real conversion path. Every ordered pair of served versions has a registered conversion, built from the standard conversion primitives, an identity, field-preserving conversion as the baseline plus specific converters for renames, list-to-object reshaping, type changes, and newly introduced fields, and structural changes are recorded in a registry rather than hand-rolled per resource so they stay reviewable. The conversion strategy must be webhook whenever any two served versions differ in schema: the `None` strategy only rewrites the `apiVersion` and leaves the object body untouched, which silently corrupts data when the schemas are not identical. A version introduced without complete conversions is a version that cannot be safely read or written.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A registered conversion for every served-version pair, built from the standard primitives and recorded in a registry; conversion strategy `Webhook` whenever served schemas differ | Introducing `v1beta2` registers `v1beta1`<->`v1beta2` conversions and sets webhook conversion | A two-version CRD with differing schemas uses the `None` strategy, or a version ships missing a pairwise conversion |

### EVO-5 — Lossless round-trip with data preservation

Conversions must be exact inverses, so no data is lost when an object is converted between versions, which the API server does routinely: it stores at one version and converts on read to whatever version a client requests, so a stored object may be converted down to an older version and back on every cycle. The subtle case is a field that exists in a newer version but has no representation in an older one; a naive conversion drops it on the way down and cannot restore it on the way up, losing the field permanently. Such fields must be preserved across the round trip: the standard technique is to store the otherwise-unrepresentable value in an annotation when converting to the version that lacks the field and restore it when converting back, so the newer version survives a trip through the older one intact. This is verified by round-trip testing over generated inputs that populate newer-version-only fields, so a dropped field fails a test rather than surfacing as silent data loss in a user's cluster.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Bidirectional conversion that preserves otherwise-unrepresentable fields across the round trip (e.g. via annotations); round-trip tests over generated inputs, including newer-version-only fields, return identical objects | A field added in `v1beta2` is stashed in an annotation when converting to `v1beta1` and restored on the way back, and the round-trip test asserts identity | A `v1beta2`-only field is dropped when converting through `v1beta1`, or the round-trip test never populates it |

### EVO-6 — Single storage version

A resource has exactly one storage version at a time, the version objects are actually persisted as; every other served version is a conversion of it. This is a Kubernetes invariant and it is what makes the conversion machinery coherent: there is one canonical stored form, and every read and write converts to and from it. The storage version must be able to represent every field of every served version without loss, because it is the hub through which all data passes, which in practice means the storage version is the newest and most expressive version. Serving zero or multiple storage versions is invalid.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Exactly one version marked storage; the storage version can represent all served versions losslessly | The newest served version is the single storage version | Two versions are marked storage, or the storage version cannot represent a field of another served version |

### EVO-7 — Storage promotion lags introduction

A newly introduced version must be served but not made the storage version in the same release that introduces it; storage promotion happens in a later release. This is the property that makes provider downgrades safe. The moment a version becomes the storage version, objects begin to be persisted in its schema, and any controller or API server that does not understand it, including the immediately prior provider release a user might roll back to, can no longer read those objects. By introducing a version as served-only first and promoting it to storage only after it has shipped in a prior release, the version is guaranteed to be understood by the release a user would downgrade to, so a rollback within the support window can still read everything in storage. Promoting storage in the same release as introduction collapses that window and turns any rollback into unreadable data.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A version is served-only in the release that introduces it; storage promotion occurs in a subsequent release | `v1beta2` is introduced served-only in release N; storage is promoted to `v1beta2` in release N+1 | `v1beta2` is introduced and made storage in the same release, so a rollback cannot read newly stored objects |

### EVO-8 — Downgrade safety

The immediately prior supported provider release must be able to read every object the current release can write to storage. Upgrades are routinely rolled back, and a rollback that cannot read what the newer release stored is an outage: the prior controller fails to decode objects and cannot reconcile them. This property follows from three rules operating together, bidirectional lossless conversion (EVO-5), a storage version the prior release understands (EVO-7), and one canonical storage version (EVO-6), but it must be stated and tested directly rather than assumed, because it is the user-facing guarantee those mechanics exist to provide. It is verified by a downgrade test that writes objects with the current release and reads them at the prior release's served version.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| The prior supported release reads all objects the current release can store; verified by a downgrade read test | Objects written by release N are read successfully by release N-1 at its served version | An object stored by the current release is unreadable by the prior release |

### EVO-9 — Safe version removal

A version may be removed from a resource only after every object stored at it has been migrated to a still-served version and the version has been cleared from the CRD's `status.storedVersions`. Kubernetes records in `status.storedVersions` every version ever used to persist an object, and it refuses to remove a version from `spec.versions` while it still appears there, because those stored objects would become unreadable. Removal therefore has a required sequence: ensure the version is no longer the storage version (EVO-6 and EVO-7 already provide a newer one); migrate the objects still stored at it by rewriting them at the current storage version, which a storage-version migration can drive; remove the retired version from `status.storedVersions`, which is a deliberate write the API server does not perform automatically; and only then drop the version from `spec.versions`. Skipping the migration or the `storedVersions` update either strands data or is rejected by the API server. Note that `storedVersions` is conservative and is not a live index of etcd, so it is cleared explicitly after migration completes, not inferred.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Removal only after migration of stored objects to a served version and explicit removal of the retired version from `status.storedVersions`; a storage-version migration runs as part of the retiring upgrade | `v1beta1` is migrated to the current storage version, removed from `status.storedVersions`, then dropped from `spec.versions` | `v1beta1` is dropped from `spec.versions` while still present in `status.storedVersions`, rendering stored objects unreadable |

### EVO-10 — Deprecate before removal

A version is deprecated before it is removed, giving users notice and time to migrate. Deprecation marks the version deprecated, names the release in which it was deprecated, and surfaces a warning to clients that use it, while the version continues to be served throughout a documented window so existing automation keeps working. Removal follows only after the window has elapsed and the safe-removal sequence in EVO-9 is complete. Removing a version that clients still use without this notice is a silent break; the deprecation process turns an eventual removal into an announced, predictable transition.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Deprecation marker plus named release plus client-facing warning plus served window; removal only after the window and the EVO-9 sequence | `v1beta1` is deprecated in a named release, served through its window, then removed via the safe-removal sequence | A served version is removed with no prior deprecation or window |

### EVO-11 — Versioning review gate

The versioning rules are enforced at merge time, not left to author diligence. Every change is checked for breaking impact against the currently served schema, and a flagged break must be resolved by introducing a new version rather than overridden; every newly introduced version must ship with its complete set of conversions and passing round-trip tests before it can merge; and storage-version and `storedVersions` transitions are reviewed against EVO-6 through EVO-9. This gate is the safety net for the entire evolution contract, so it must not be suppressed to land a change faster. Whether an individual check is advisory or blocking is a repository policy choice, but the review that turns a flagged break into a new version is mandatory.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A pre-merge breaking-change check against the served schema; new versions blocked without complete conversions and passing round-trip tests; storage and `storedVersions` transitions reviewed | A PR that would break `v1beta1` is flagged and reworked into `v1beta2` with conversions and round-trip tests before merge | A breaking change merges with the check suppressed, or a new version merges without conversions or round-trip tests |

## Generation determinism

### GEN-1 — Reproducible

Where a provider is generated rather than hand-written, generation must be deterministic: the same inputs must produce identical output on every run and every machine. This requires that every source of nondeterminism be pinned, map iteration ordered, collections sorted, and timestamps, hostnames, and absolute paths kept out of generated content, so regeneration is a pure function of its inputs. It matters because a generated provider is too large to review by reading; reviewers rely on the diff between the previous generation and the new one to see what changed. If generation is nondeterministic, every regeneration produces incidental churn that buries the real change, and no reviewer or agent can distinguish an intended API change from noise. Determinism is therefore what makes a generated provider reviewable and diffable at all, and it is checked by regenerating in CI and asserting an empty diff.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Generation is a pure function of its inputs; regeneration yields identical output | Regenerating on two machines produces no diff | Regeneration reorders fields or embeds a timestamp, producing spurious diffs |

### GEN-2 — No hand-edits

In a generated provider, generated artifacts must never be hand-edited; any correction must be made in the generator or its configuration so it survives regeneration. A generated file carries no memory of manual changes: the next time the provider is regenerated, the generator overwrites the file from its inputs, and any hand-edit is silently lost, taking with it whatever fix or behavior it encoded. Worse, the loss is invisible until something breaks, because the edit disappears at the next unrelated regeneration rather than at the time it was made. The rule keeps the generator the single source of truth: a wrong field type is fixed by adjusting the resource's configuration so the generator emits the correct type, not by editing the emitted file, so the fix is durable and reproducible under GEN-1.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| All corrections made in the generator or its configuration; generated files never edited by hand | A wrong field type is fixed by changing generator configuration | A generated file is edited directly, and the change is lost at the next regeneration |

## Packaging and supply chain

### PKG-1 — Valid package

A provider must be distributed as a valid package carrying complete and accurate metadata, because the package is how the platform discovers, installs, and runs it. That metadata declares the provider's identity, its capabilities, its runtime requirements, and any provider-family membership that governs how it coexists with sibling packages, and the install machinery relies on all of it being correct. Incomplete or wrong metadata is not a soft failure: it can block installation outright, cause the wrong runtime configuration to be applied, or break coexistence with related packages in the same family. A valid, well-described package is the precondition for every consumer-side operation the platform performs on the provider.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A valid package with complete, accurate metadata including capabilities and family membership | The package declares its family and installs and coexists with sibling packages | Missing or incorrect metadata blocks install or breaks family coexistence |

### PKG-2 — Signed and attested

Every release artifact must be cryptographically signed and accompanied by provenance attestation and a software bill of materials, so a consumer can verify what they are running and where it came from before admitting it to a cluster. The signature establishes authenticity and integrity, that the artifact is the one the maintainers published and has not been tampered with; the attestation records how and from what sources it was built; and the SBOM enumerates its components so consumers can assess exposure to known vulnerabilities. This is the baseline supply-chain posture regulated and security-conscious environments require, and increasingly the default expectation everywhere. An unsigned or unattested release cannot be verified and forces consumers to trust it blindly.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Signature plus provenance attestation plus software bill of materials on every release artifact | A consumer verifies the signature and reviews the SBOM before admitting the package | A release ships unsigned, or without an SBOM or attestation |

### PKG-3 — Vulnerability response

Known vulnerabilities in the provider and its dependencies must be tracked and patched on a defined cadence, and a patched release must itself satisfy every other rule here, including signing and attestation under PKG-2. A provider is long-lived and its dependency tree accrues disclosed vulnerabilities over time; the rule requires these be monitored and remediated within a stated window rather than deferred to whenever the next major release happens. Because the patch path is also where automated remediation tends to operate, it is held to the same conformance bar as any other change: a security patch that skips tests, signing, or attestation trades one risk for another. Timely, verifiable remediation is what keeps an installed provider safe over its supported life.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Vulnerabilities tracked; a patched, signed, attested release produced within the defined window | A disclosed dependency vulnerability is patched and re-released within the window | A known vulnerability is left unpatched past the window, or the patch skips signing |

## Observability and status

### OBS-1 — Standard conditions

A provider must report the standard readiness and sync conditions, using the standard reasons, and those conditions must reflect real external state rather than local reconcile progress. Readiness reports whether the external resource actually exists and is usable, with reasons distinguishing available from the transient creating and deleting states; sync reports whether the provider is successfully reconciling the resource, with reasons distinguishing success, error, and paused. Because these condition types and reasons are identical across every provider, tooling, composition readiness checks, and operators can reason about any resource's health uniformly without provider-specific logic. The critical constraint is that readiness must track external reality: marking a resource ready before it is genuinely usable causes dependents to proceed against a resource that is not there, which is exactly the failure the readiness condition exists to prevent.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Readiness reasons: available, creating, deleting. Sync reasons: success, error, paused. Conditions reflect real external state | Readiness is false with reason creating during provisioning and true with reason available once the resource is usable | Readiness is reported true before the external resource is actually available |

### OBS-2 — Standard metrics

A provider must emit the standard resource-level metrics, unmodified, so a single monitoring setup works across the entire fleet regardless of which providers are installed. These cover the reconcile lifecycle, time to first reconcile and time to readiness, along with drift, deletion duration, and the volume and latency of external API calls, and because they are named and shaped identically everywhere, one dashboard or alert can aggregate them across providers. Renaming, dropping, or altering these metrics breaks that uniformity and forces per-provider monitoring, which does not scale as the number of installed providers grows. The metrics are inherited by building on the standard runtime; the rule is that a provider must not suppress or replace them.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Standard resource metrics, unmodified: time to first reconcile, time to readiness, drift, deletion, external-call volume and latency | One dashboard graphs time-to-readiness uniformly across every installed provider | A provider renames or omits the standard metrics, breaking fleet-wide monitoring |

### OBS-3 — Events

A provider must emit Kubernetes events for significant lifecycle transitions and for reconcile errors, with enough detail to convey cause, so an operator can understand why a resource is in its current state without attaching to controller logs. Events are the user-facing record attached to the object itself; a well-placed event saying a create failed because a quota was exceeded turns an opaque stuck resource into a self-explaining one. The alternative, surfacing failures only in controller logs, requires cluster-level log access and correlation that most users operating a single resource do not have. Events make the provider's behavior legible at the level of the object the user actually interacts with.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Events on significant lifecycle transitions and on reconcile errors, carrying the cause | An event on the resource states "cannot create: quota exceeded" | A create failure is visible only in controller logs, not on the object |

## Security

### SEC-1 — Least privilege

A provider must request only the permissions it actually needs and must document what it requires and why. The provider's credentials are a high-value target, and the blast radius of a compromised or misbehaving provider is bounded by the permissions it holds; a provider scoped to exactly the services and actions it manages contains that radius, while one granted broad administrative access turns any failure into a potential account-wide incident. Documenting the required permissions lets operators review and grant them deliberately rather than over-provisioning out of uncertainty. Least privilege is both a security requirement and an operability one, since a clearly scoped permission set is auditable in a way a broad grant is not.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Minimal scoped permissions, with a documented rationale for what is required | An object-storage provider deployment requests only storage permissions | The deployment requests account-wide administrative access |

### SEC-2 — No secret leakage

Sensitive values, credentials, tokens, generated passwords, and private keys, must never appear anywhere except the connection secret. In practice this means keeping them out of the managed resource's spec and status, out of events, and out of logs at every verbosity level, including the debug and trace paths often added during troubleshooting and forgotten. The managed resource object and its events are readable by anyone with get and list access at that scope, a far broader audience than those entitled to the credential itself, so a secret mirrored into status is effectively published to every operator and controller watching that resource. Logs are worse, because they are routinely shipped to aggregation systems with looser access controls and long retention. The connection secret is the one surface designed to hold this data under Kubernetes secret access controls, and sensitive values must be confined to it end to end, from the moment the provider observes or generates them.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Sensitive values confined to the connection secret; absent from spec, status, events, and logs at every verbosity | A generated password is written only to the connection secret | A credential is echoed to logs at debug verbosity, or mirrored into status |

## Testing

### TST-1 — Lifecycle proof

Every resource that can be tested must pass an end-to-end lifecycle test that exercises the four behaviors most likely to be wrong, against a real external system. The test creates the resource and waits for it to become ready, proving create and observe agree; updates a field and waits for reconvergence, proving drift is detected and updates apply; imports the resource by clearing its local state and asserting the provider re-adopts the live external resource from its external name alone, proving identity; and deletes it, asserting the external resource is actually removed rather than leaked. Each step maps to a specific runtime rule, and the import step in particular is the executable check on RT-1 that a create-only test cannot provide, since only import forces the provider to rediscover a resource from its external name with no cached state. This is how conformance is proven rather than asserted: a violated runtime rule fails a concrete step instead of surfacing later in a user's cluster.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Four steps pass against a live system: create then ready; update then reconverge; import (local state cleared) then re-adopt from external name; delete then external resource gone | All four steps pass, including re-adoption on import | The import step creates a duplicate instead of re-adopting the existing resource |

### TST-2 — Conversion proof

Every conversion between API versions must be covered by automated round-trip tests over generated inputs, so a lossy conversion fails in CI rather than in a user's cluster. The test generates arbitrary valid objects, converts them across each served-version pair and back, and asserts the result is identical to the original, which is the executable form of the lossless-conversion guarantee in EVO-5. Fuzzing the inputs matters because hand-written test cases tend to miss exactly the fields and edge combinations where conversions silently drop data; generated inputs exercise the whole schema. Without this test, a conversion defect is invisible until an object round-trips through the API server in production and loses a field permanently.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Automated round-trip tests over generated inputs across every served-version pair, asserting identical results | Every version-pair round-trip returns an identical object in CI | A lossy conversion is merged because no round-trip test exercises the affected field |

### TST-3 — Examples

Every resource must ship a deployable, dependency-complete example, because that example is simultaneously the input the lifecycle test runs and the starting point users copy. Dependency-complete means the example brings everything it needs to apply cleanly: a resource that references another, a subnet needing a network, ships alongside a generated example of that dependency, so applying it succeeds without the user hunting for prerequisites. The example doing double duty is what keeps documentation and test coverage honest, since an example that does not actually apply fails the lifecycle test and is caught immediately. An incomplete example that references something undeclared is both a broken test fixture and a broken piece of documentation.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A deployable example per resource, including generated examples of its dependencies, that applies cleanly | A subnet example ships with a generated example of the network it depends on and applies cleanly | An example references an undeclared dependency and fails to apply |

### TST-4 — Declared exceptions

Any resource that cannot meet a testing requirement must declare the exception explicitly, with a reason, rather than shipping untested and unmarked. Some resources genuinely cannot be exercised in ordinary CI, they provision something too expensive, require hardware or entitlements the test environment lacks, or have irreversible side effects, and the rule does not pretend otherwise. What it requires is that the gap be recorded in a coverage register with a stated reason, so untested behavior is a visible, tracked risk that can be reviewed and is expected to shrink over time, rather than a silent hole no one is accountable for. The difference between a declared exception and an undeclared gap is the difference between a known risk and an unknown one.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A coverage-register entry with a stated reason for each untested resource; the register is expected to shrink over time | A resource that provisions expensive dedicated hardware is listed as untested with a reason | A resource ships without test coverage and without any recorded exception |

## Governance and maintenance

### GOV-1 — Named ownership

Every provider must declare its maintainers and its review owners, so responsibility for the provider is explicit and durable. A provider is a long-lived artifact that will need reviews, releases, deprecations, and vulnerability response for years, and each of those requires someone accountable; an ownership record names who that is, both for approving changes and for cutting releases. Without declared ownership, a provider drifts into an unmaintained state where security patches stall and reviews have no responsible party, which is precisely the failure that erodes trust in an ecosystem of many providers. Named ownership is the governance precondition that makes the maintenance rules that follow enforceable.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| A declared ownership record naming maintainers and review owners | An owners record names the maintainers accountable for reviews and releases | The provider has no declared owner or reviewers |

### GOV-2 — Supported releases

Releases must come from maintained release lines so fixes and security patches can be backported to the versions users are actually running, rather than being available only on the latest development branch. Users pin to released versions for stability and cannot always adopt the newest minor immediately, so a fix that exists only at head is effectively unavailable to them; maintaining release lines lets a critical fix or security patch be delivered to supported versions without forcing an upgrade that carries unrelated change. This is the same support model mature projects use, and it is what lets an organization run a provider in production with confidence that a vulnerability will be patched on a version they can actually deploy. The set of supported lines and their support window should be explicit.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Maintained release lines; fixes and security patches backported to supported versions | A security fix is backported to the supported release lines, not only to the development branch | Fixes land only at head, forcing users onto the latest to get them |

### GOV-3 — Maintenance parity

Maintenance changes must meet the same conformance bar as new work, with no lighter standard for an upgrade, a patch, or a release cut. It is tempting to treat routine maintenance, an upstream schema bump, a dependency update, a backport, as lower-risk and wave it through with less scrutiny, but these changes touch the same API surface and runtime behavior new resources do and can break the same contracts, including API stability and conversion correctness. The rule closes that gap by subjecting every change to the same gate: an upstream schema bump passes the same lifecycle and conversion tests a brand-new resource would, and a backport is held to the same standards as the original. Maintenance parity is what prevents conformance from decaying over time through the accumulation of under-reviewed maintenance changes.

| Accepted values | Conformant | Non-conformant |
|---|---|---|
| Every maintenance change passes the full conformance gate, identical to new work | An upstream schema bump passes the same lifecycle and conversion tests as a new resource | A dependency or schema change is merged through a lighter maintenance path that skips the gate |

## Applicability

- **Authors and agents:** these rules are the specification an author builds against and the gate it is judged by, person or agent. Author identity, language, and engine do not change the rules or the gate.
- **Definition of done:** every rule satisfied and proven, with any exception declared under TST-4.
- **One bar:** identical for internal, external, community, partner, and agent authors. There is no lighter standard for community providers and no separate standard for internal work.

---

# Addendum (Internal): Conformance Roadmap

*Internal; not part of the contributor-facing rules above.*

- **Risk:** much of what makes a provider correct today is inherited implicitly from the underlying engine (external-name and import semantics, drift detection, ordering and dependency handling, not-found detection, lossless conversion). A new engine that does not make these explicit diverges in ways that break composition, secrets, drift, and data integrity.
- **Plan:** (1) keep the rules engine-agnostic, as properties not mechanisms; (2) build a conformance suite mapping each rule ID to a check that fails when the rule is violated, across all areas; (3) hold current providers to the suite first, to confirm it is correct against providers we already trust; (4) build any new engine against the same bar.
- **Principle:** the engine changes; the rules do not. Enforcing them now, while the current engine is the only one, makes an eventual engine change a swap rather than a rewrite.
