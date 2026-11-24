# What the provider schema does and does not tell you

[`control-plane-project-charter` §6](../../SKILL.md#6-the-provider-schema-is-a-lower-bound-not-the-constraint-set) states the rule.

---

**A v2-conformant composition can still emit a resource the cloud API rejects.** S3 lifecycle
rules with neither `filter` nor `prefix` pass composition tests and fail with `MalformedXML`.

**What the models do record.** Some generated models carry conditional rules the type system
cannot express, in docstrings and field descriptions: *"Required if
`source_db_instance_identifier` is not specified"*, *"Conflicts with `domain_fqdn`,
`domain_ou`"*, *"If set, must contain at least one key-value pair"*. A field being optional in
the generated type means only that the **CRD**'s schema does not mark it required — a CEL rule in
the CRD, or the provider, still can.

**The CRDs carry those CEL rules** (§6: where `up` caches them, and the grep that lists them).
Their `x-kubernetes-validations` require parameters the generated model leaves optional
(`spec.forProvider.versioningConfiguration is a required parameter`, provider-aws-s3 v2.8.2).

**Expect this to be sparse, not systematic.** Measured over the namespaced AWS models in a real
project: `Conflicts with` in 12 of 127 Kinds, `Required if` in 3, clustered in the big Kinds like
RDS `Instance`. The grep is cheap and worth running, but **finding nothing is not evidence the
API has no such rule.**

One false positive to filter out: *"At most one of each condition type may apply"* appears in
269 of 281 model files. It is the Kubernetes `Condition` docstring in every resource's *status*
block, not a provider input constraint.

The structural question the models cannot answer: **when an XR field is a list, is one
resource — or one rule — per element correct for this API?** (§6: a decision you
justify, not the default.) These rule classes live only in the cloud API, never in a CRD schema:

| Class of rule | Example | Where it is written down |
|---|---|---|
| Uniqueness / non-overlap across a list | two S3 lifecycle rules whose filters both match the same prefix | AWS API docs only |
| Mutually exclusive combinations | a Table with both on-demand billing and provisioned throughput | AWS API docs only |
| Ordering and dependency | a policy referencing a role that does not exist yet | provider behaviour |
| Account- or region-scoped limits | one bucket-lifecycle configuration per bucket, not one per rule | AWS API docs only |

For S3 lifecycle the answer is a single `BucketLifecycleConfiguration` holding N rules, and
the rules must not overlap — a loop that emits one configuration per rule is wrong twice
over, and renders perfectly.
