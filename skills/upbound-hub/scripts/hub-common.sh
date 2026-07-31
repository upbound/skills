#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers, sourced by the other hub-* scripts. Not useful on its own.
#
# The reason this exists: an agent cannot `export` a variable into the user's
# shell, so relying on HUB_API_URL being in the environment would force the user
# to run setup commands by hand before asking a question. Persisting the URL
# instead lets the agent do the whole setup itself, once.

hub_config_file() {
  printf '%s/upbound/hub.env' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

# A URL with no whitespace and no control characters. A newline would let a
# crafted value append a second HUB_API_URL= line to the config, or inject a
# second `server:` key into the generated kubeconfig, redirecting the bearer
# token to another host.
hub_valid_url() {
  case "$1" in
    *[[:space:]]* | *$'\n'* | *$'\r'*) return 1 ;;
  esac
  case "$1" in
    https://[A-Za-z0-9]*) return 0 ;;
    http://[A-Za-z0-9]*)
      if [ "${HUB_INSECURE:-0}" = "1" ]; then
        echo "warning: using http://; the bearer token is sent in cleartext" >&2
        return 0
      fi
      echo "error: refusing http:// -- the bearer token would be sent in cleartext." >&2
      echo "  Set HUB_INSECURE=1 to allow it. Development only." >&2
      return 1 ;;
  esac
  return 1
}

# Resolve HUB_API_URL from the environment first, then the config file. The
# environment wins so a one-off override still works.
hub_resolve_url() {
  if [ -n "${HUB_API_URL:-}" ]; then
    if ! hub_valid_url "$HUB_API_URL"; then
      echo "error: HUB_API_URL is not a usable URL" >&2
      return 1
    fi
    HUB_API_URL="${HUB_API_URL%/}"
    export HUB_API_URL
    return 0
  fi

  local config
  config="$(hub_config_file)"
  [ -f "$config" ] || return 0

  local found
  # head, not tail: if a crafted value ever appended a second line, the first
  # one is the one that was validated.
  found="$(sed -n 's/^HUB_API_URL=//p' "$config" | head -1)"
  if [ -n "$found" ]; then
    if ! hub_valid_url "$found"; then
      echo "error: $config holds an invalid HUB_API_URL. Re-run hub-setup --url" >&2
      return 1
    fi
    HUB_API_URL="${found%/}"
    export HUB_API_URL
  fi
}

hub_save_url() {
  local url="$1" config
  hub_valid_url "$url" || return 1
  config="$(hub_config_file)"
  mkdir -p "$(dirname "$config")"
  # Rewrite rather than append, so repeated setup runs do not accumulate lines.
  if [ -f "$config" ]; then
    grep -v '^HUB_API_URL=' "$config" > "$config.tmp" 2>/dev/null || true
    mv "$config.tmp" "$config"
  fi
  printf 'HUB_API_URL=%s\n' "$url" >> "$config"
  printf '%s\n' "$config"
}

# hub-setup downloads the helper rather than the repository committing it, so on
# a fresh checkout it is simply absent. Without this the caller gets bash's
# "No such file or directory" and exit 127, which names a path but not the fix.
hub_require_helper() {
  local bin="$1"
  [ -x "$bin" ] && return 0

  if [ -e "$bin" ]; then
    echo "error: the Hub credential helper is not executable: $bin" >&2
  else
    echo "error: the Hub credential helper is not installed." >&2
  fi
  cat >&2 <<'EOF'

  Run: scripts/hub-setup

  It downloads the helper, checks it against a published SHA-256, and signs in.
EOF
  return 1
}

hub_require_url() {
  hub_resolve_url
  [ -n "${HUB_API_URL:-}" ] && return 0

  cat >&2 <<'EOF'
error: no Hub API URL configured.

  Ask the user for their Upbound Hub API endpoint, then save it once:

    scripts/hub-setup --url https://hub.example.com

  Setting HUB_API_URL in the environment also works, and takes precedence.
EOF
  return 1
}
