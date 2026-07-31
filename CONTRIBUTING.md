# Contributing

Thanks for helping improve these skills. A skill that stops one specific mistake is worth more than a
long one that surveys a topic, so small contributions are welcome.

## Setup

You need `git`, `bash`, and `python3` 3.9 or newer. `shellcheck` and `bats` are only needed if you touch
a skill's shell scripts; `make golden` additionally needs PyYAML. Note that `make hooks` sets
`core.hooksPath`, which takes precedence over any hooks you already have installed.

```bash
git clone https://github.com/<you>/skills      # your fork
cd skills
make hooks
```

`make hooks` points `core.hooksPath` at `hack/hooks` and installs two guards:

- **pre-commit** blocks a commit that would add something shaped like a credential.
- **commit-msg** blocks model co-author trailers. It does not check the sign-off; that runs in CI.

Run it before your first commit. Once a secret is committed it is in your reflog and in every clone, and
getting rid of it means rewriting history — CI catching it afterwards is already too late.

If the credential check is wrong about your change, commit with `--no-verify` and add the case to
`hack/denylist/secrets-allow.txt` in the same pull request, so the next person is not blocked. That
allowlist only suppresses the fuzzy "looks like an assigned secret" rule; a recognized token format —
an AWS key, a GitHub token, a private key header — cannot be waved through.

## Commits

Every commit needs a sign-off:

```bash
git commit -s -m "fix: correct the resource pagination ceiling"
```

The `-s` adds a `Signed-off-by:` trailer. It certifies that you wrote the change, or have the right to
submit it, under the [Developer Certificate of Origin](https://developercertificate.org/). There is no CLA.

Write subjects in the imperative mood, following
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). This repository publishes no
changelog and cuts no releases, so `git log` is the only record of what changed and why.

### No model co-author trailers

Do not add trailers crediting a model or coding agent:

```
Co-authored-by: Claude <noreply@anthropic.com>          # rejected
Generated with [Claude Code]                             # rejected
```

CI rejects these on every commit in a pull request, and on the pull request body, since GitHub composes the
squash-merge message from it.

The reason is the sign-off. Signing off is an attestation by a person who takes responsibility for the
change; a model cannot make that attestation, so crediting one as an author misrepresents who stands
behind the contribution. Use whatever tools you like to write the code — just sign for it yourself.

**Trailers naming humans are fine and expected.** GitHub adds `Co-authored-by:` automatically when you
squash-merge a pull request with several authors, or when a maintainer accepts a review suggestion. The
check matches known model identities, not the trailer itself. If it ever fires on a real person or a bot
you want to keep, add the identity to `hack/denylist/coauthors-allow.txt` in the same pull request and say
why.

If a commit is already written, fix it with `git rebase -i origin/main` and reword, or for a single-commit
branch:

```bash
git reset --soft origin/main && git commit -s
```

## Adding a skill

1. Create `skills/<name>/SKILL.md`. The directory name and the frontmatter `name` must match.
2. Write the frontmatter — see the contract below.
3. Put anything long in `skills/<name>/references/<topic>.md` and link it from `SKILL.md`.
4. Run `make readme` to regenerate the skills table in the README.
5. Run `make check`, `make lint`, and `make test`.
6. Try it: `claude --plugin-dir .` from the repo root, then ask the question the skill should trigger
   on. Keep the transcript.

Push the branch to your fork and open a pull request against `upbound/skills:main`, pasting that
transcript. It is the part review cares about most: a skill can pass every check and still fail to
trigger, or trigger and give bad advice, and the only way to know is to use it.

Do not edit `version` in `.claude-plugin/plugin.json`. A workflow bumps it after merge — patch for an
edit, minor for a new skill, major for a removal.

### Frontmatter contract

| Field | Required | Rules |
|---|---|---|
| `name` | required | lowercase kebab-case, 64 characters or fewer, equal to the directory name |
| `description` | required | one line, 40–1024 characters, naming the phrases that should trigger it. Must not begin with "proactively" |
| `license` | optional | SPDX identifier, matching the repository license |
| `references` | optional | paths relative to the skill directory, e.g. `references/querying.md` |

Nothing else is permitted. `allowed-tools`, `model`, `context`, `agent`, `user-invocable`, `metadata`, and
`version` are all rejected. They either mean nothing outside Claude Code — so a skill relying on them
behaves differently per agent, silently — or duplicate state that already lives in `plugin.json`.

CI also checks a handful of things the table cannot show:

- The first line after the frontmatter is an H1.
- Every file in `references/` is linked from `SKILL.md`. An unlinked reference is never read.
- Every script is mentioned in some `.md` in its skill, has a shebang, is executable, and carries an
  `SPDX-License-Identifier` header.
- Links resolve, are relative, and do not point outside the skill's own directory.
- No private hostname, RFC1918 address, private key, or JWT-shaped string appears in any tracked file.
  A redacted transcript containing a `10.x` address will trip this; quote it differently or add a case
  to `hack/denylist/strings-allow.txt`.

Frontmatter must also be simple YAML: flat `key: value` pairs and plain lists. No nested mappings, no
`{}`/`[]`, no `|` or `>` blocks, no tabs. If a value contains a colon followed by a space, quote it —
otherwise YAML reads it as a nested key and the skill loads with no metadata at all. The validator
enforces this. It is the failure mode with no symptom: nothing errors, the skill just never triggers.

### Writing a description

The description is the only thing an agent sees when deciding whether to load your skill. Everything else
is invisible until it does.

- Say what the skill lets the agent do, then when to load it, then what it covers.
- Name the words a user would actually type, including wrong ones. If people still say "claim" for
  something that no longer exists, keep "claim" in the description — the skill is where they find out.
- If another skill is nearby, say so explicitly: "Not for X — use `other-skill`."
- No boolean logic. `A AND (B OR C)` is not evaluated; it is matched as prose, so two skills whose
  descriptions differ only by a condition get picked between arbitrarily. If a condition is needed to
  choose, they should be one skill with a decision tree in the body.
- Do not open with "PROACTIVELY use this skill when". It spends the most valuable words in the description
  on an instruction rather than on what the skill does.

### Progressive disclosure

`SKILL.md` is loaded whenever the skill triggers, so it should hold what is needed nearly every time: what
the thing is, how to set it up, when to use it, and the mistakes to avoid. Keep it to 500 lines or fewer.

Everything else goes in `references/`, linked from `SKILL.md` with a note on when to read it:

```markdown
- [querying.md](references/querying.md) — read before writing any query with filters or pagination
```

Keep hard "never do this" rules in `SKILL.md` rather than a reference file. A constraint only works if it
is in context at the moment it would be violated.

### Scripts

A skill may ship scripts under `skills/<name>/scripts/`, but prefer prose. Prose works in every agent and
does not need review for shell injection. Reach for a script when the agent would reliably get it wrong by
hand — multi-call pagination, credential handling, deterministic output shaping.

- Never put a secret in a command argument. Anything on the command line is visible to every process on
  the machine via `ps`. Pass credentials through stdin or a `0600` file in `mktemp -d` with a `trap` to
  clean up.
- Verify downloads against a checksum. Never pipe a download into a shell.
- `set -euo pipefail`, a shebang, and the executable bit.
- Resolve paths from the script's own location, `dir="$(cd "$(dirname "$0")" && pwd)"`, never from the
  working directory or an agent-specific variable.
- Support `--help`, exiting 0 without touching the network.
- Bash or standard-library Python only. No `npm install` or `pip install` at runtime.

## Writing style

Documentation here should read like a person wrote it for another person.

- Skip "delve", "leverage", "robust", "seamless", "comprehensive", "it's worth noting". No sentence
  starting "Whether you're…".
- Two items are fine. Not everything needs three, and not every third phrase needs bolding.
- Give the reason, not a restatement. "The API caps pagination at page 20" beats "it is important to be
  aware of pagination limits."
- Prefer a specific number to a hedge. "Roughly 13% of records carry conditions" is useful; "some records
  may not have conditions" is not.
- Read it aloud. If it sounds like a press release, rewrite it.

## Pull requests

Pull requests need a review from a maintainer. CI must be green: `hack/validate.py`, the unit and script
tests, shellcheck and SPDX headers, the credential and commit-trailer checks, gitleaks and semgrep, and
`claude plugin validate` against both manifests.

Keep them focused. A pull request that fixes one wrong instruction is easier to review, and lands faster,
than one that reorganizes a skill and fixes the instruction along the way.

## Reporting problems

- A skill gives bad advice, or does not trigger when it should — open an issue with the "Skill bug"
  template. Include what you asked and what the agent did.
- Something is missing — use the "Skill request" template.
- A security issue — see [SECURITY.md](SECURITY.md). Do not open a public issue.
