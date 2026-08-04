# Upbound Skills

The [Upbound Platform](https://upbound.io) manages a fleet of Kubernetes control planes,
[Crossplane](https://crossplane.io) or otherwise. These skills teach a coding agent to query
and change that fleet correctly — which mostly means stopping it from confidently reporting
numbers that are wrong.

[Agent Skills](https://agentskills.io/) are instructions an agent loads when a task matches
them.

## Install

Claude Code is the supported agent today.

```
/plugin marketplace add upbound/skills
/plugin install upbound@upbound
```

`marketplace add` registers the source; `install` adds the plugin. Once this lands in
Anthropic's plugin directory, `/plugin install upbound@claude-plugins-official` will be
enough on its own.

To try it without installing:

```bash
git clone https://github.com/upbound/skills upbound-skills
claude --plugin-dir upbound-skills
```

## Updating

```bash
claude plugin marketplace update upbound   # refresh the source
claude plugin update upbound@upbound       # then the plugin; restart to apply
```

`claude plugin list` shows the version you are on, and the version here is bumped on every
merge that touches `skills/`.

Worth doing rather than leaving to drift. A skill is instructions, so an out-of-date copy
does not fail — it keeps confidently answering from whatever it last knew, including
endpoints and field names that have since been corrected.

### Other agents

Not supported yet, though the skills carry no vendor-specific frontmatter, so copying
`skills/upbound-hub/` into another agent's skills directory should load. Nothing here is
tested against another agent, and the scripts assume `bash`, `curl`, `jq`, and `column`.

Adding an agent means a manifest alongside `.claude-plugin/`; the layout is arranged so it
moves no files.

## Prerequisites

| Skill | Needs |
|---|---|
| `upbound-hub` | `bash`, `curl`, `jq`, `column`, `shasum`; `kubectl` only for writes |

On first run the skill downloads a credential helper from `storage.googleapis.com` and
checks it against a published SHA-256. It asks once for your Hub API endpoint and saves it,
so there is nothing to set up in advance.

## Quick start

Install the plugin, then ask your agent an ordinary question:

> **How many resources are unhealthy across the fleet?**

The agent runs setup itself — installing the credential helper, verifying its checksum, and
signing you in. It asks once for your Hub API endpoint and remembers it.

Then it loads `upbound-hub`, queries the aggregation endpoint rather than paging 40,000
records, and answers with two denominators: how many resources exist, and how many actually
carry health conditions. Most do not, so a single percentage would be wrong. Without the
skill, agents report one anyway.

More questions it handles:

> **List the control planes and group them by phase.**
>
> **What CRDs and XRDs do we have for AWS?**
>
> **Show me the unhealthy resources in prod-1.**

## Skills

<!-- BEGIN skills-table -->
| Skill | What it is for |
|---|---|
| [`provider-conformance-validator`](skills/provider-conformance-validator/SKILL.md) | Validate a Crossplane or Upjet provider repository against the provider conformance standard and produce a conformance report. |
| [`upbound-hub`](skills/upbound-hub/SKILL.md) | Query and mutate Upbound Hub, the central API for an Upbound Platform deployment, which gives one cross-fleet view of control planes, spaces, realms, types, packages, resources, identity providers, and the image catalog. |
<!-- END skills-table -->

## How these skills are built

Each skill is a directory with a `SKILL.md` and, where it helps, `references/` and
`scripts/`.

`SKILL.md` is loaded whenever the skill triggers, so it holds what is needed nearly every
time: what the thing is, how to set it up, and the mistakes worth avoiding. Longer material
lives in `references/`, which the agent reads only when it needs to. That keeps the
always-loaded cost small without losing depth.

Frontmatter is deliberately minimal: `name` and `description`, plus optional `license` and
`references`. CI rejects everything else — `allowed-tools`, `model`, and the rest — which is
what keeps the skills portable rather than merely claiming they are.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
`make check`, `make lint`, and `make test` cover most of CI.

Skill fixes are welcome and small ones are the most valuable: if an agent gave you bad
advice, the fix is usually a paragraph.

## Security

Skills are instructions, and some ship shell scripts that run with your credentials. Read
[SECURITY.md](SECURITY.md) before installing, and report vulnerabilities privately.

## License

[Apache-2.0](LICENSE)
