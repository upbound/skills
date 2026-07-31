# Working in this repository

Instructions for coding agents. Humans should read [CONTRIBUTING.md](CONTRIBUTING.md), which covers the
same ground in more detail.

## Commits

- Sign off every commit: `git commit -s`. Contributions are made under the
  [Developer Certificate of Origin](https://developercertificate.org/), and CI rejects commits without a
  `Signed-off-by:` trailer.
- **Do not add model or agent co-author trailers**, and do not add "Generated with …" lines. A
  `Co-authored-by:` naming Claude, Codex, Copilot, Cursor, Gemini, or any other model is rejected in CI.
  The sign-off is an attestation by a person who takes responsibility for the change, and a model cannot
  make it.
  - `Co-authored-by:` naming a *human* is fine. GitHub adds it automatically on squash merges and accepted
    review suggestions.
- Write commit subjects in the imperative mood, following
  [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). This repository publishes no
  changelog, so `git log` is the record and has to read well on its own.

## Secrets

Never commit a credential. `make hooks` installs a pre-commit hook that blocks recognized
token formats and private keys. If you need a credential in an example, write it as an
environment variable reference or an obvious placeholder.

## Before pushing

Run `make check`. It runs everything CI runs. `make lint` shellchecks the skill scripts, and `make test`
runs the validator's own tests.

## Adding or editing a skill

Skills live at `skills/<name>/SKILL.md`. The frontmatter contract is deliberately small so skills stay
portable across agents:

```yaml
---
name: <lowercase-kebab, must equal the directory name>
description: <one line, 40-1024 characters, names the phrases that should trigger it>
---
```

`license` and `references` are the only other permitted keys. Anything else — `allowed-tools`, `model`,
`metadata`, `version` — is rejected. Those keys either mean nothing outside Claude Code or duplicate state
that lives elsewhere, and a skill that depends on them behaves differently per agent without saying so.

Keep `SKILL.md` under 500 lines. Longer material belongs in `skills/<name>/references/<topic>.md`, linked
from `SKILL.md` with a short note on when to read it.

Do not use agent-specific syntax in skill bodies: no `${CLAUDE_PLUGIN_ROOT}`, no tool names, no slash
commands. Reference files and scripts by paths relative to `SKILL.md`, which every agent resolves.
