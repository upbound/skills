# Security policy

## Reporting a vulnerability

Do not open a public issue or pull request for a security problem.

Report it through
[GitHub private vulnerability reporting](https://github.com/upbound/skills/security/advisories/new), or
email security@upbound.io. We aim to acknowledge within five business days.

Only the current state of `main` is supported. This repository cuts no releases, so fixes ship by merging
to `main` and are picked up on the next plugin update.

## What counts as a vulnerability here

This repository ships instructions that coding agents follow, and shell scripts those agents run on a
contributor's machine with that person's credentials. That makes the interesting failures different from a
normal library, and worth naming so they get reported rather than filed as bugs:

- **Prompt injection sinks.** Skill text, or content a skill tells an agent to fetch, that could carry
  instructions the agent then follows.
- **Credential exposure.** A script that puts a token in a command argument, writes one to a
  world-readable file, logs one, or sends one somewhere it should not go. Anything on a command line is
  readable by every process on the machine.
- **Unsafe downloads.** Fetching a binary or script without verifying it, or piping a download into a
  shell.
- **Destructive instructions.** Guidance that leads an agent to delete resources, overwrite state, or make
  an unrecoverable change without the user understanding what was about to happen.
- **Path escapes.** A skill reading or writing outside its own directory, other than a declared
  config path such as `${XDG_CONFIG_HOME:-~/.config}/upbound/`.

Report these as vulnerabilities. Ordinary wrong advice — a stale API version, a command with the wrong
flag — is a bug; use the issue tracker.

## For people using these skills

Skills are instructions, not sandboxed code. Before installing, read the skill you are installing and the
scripts it ships. Two things worth knowing about this repository specifically:

- Scripts run with your credentials and your network access, and anything they print reaches the
  agent's transcript.
- `skills/upbound-hub/scripts/hub-setup` downloads a helper binary at first run from
  `storage.googleapis.com/upbound-hub-artifacts` and checks it against a SHA-256 published alongside
  it. That checksum shares an origin with the binary, so it catches a corrupted download, not a
  compromised source.
- `HUB_CREDENTIAL_HELPER_BASE_URL` changes where that binary comes from, and is restricted to
  `https://`. `HUB_INSECURE=1` disables TLS verification. Set neither unless you know why. The
  default channel is the only supported one; other paths in that bucket are build artifacts that
  may change or disappear without notice.
