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

# ---------------------------------------------------------------------------
# Resource -> group/version resolution
#
# Hub 1.1.0 split the API surface that Hub 1.0.x served from one group. Pinning
# a group in the caller means every request against the other major silently
# builds a wrong URL, so the group is resolved the same way the version already
# was: ask the server.
#
#   1.0.x                                     1.1.0
#   hub.upbound.io      resources, lenses,    inventory.hub.upbound.io
#                       typedefinitions,
#                       crossplanepackages,
#                       resourcestats,
#                       resourcerelationship*
#   hub.upbound.io      controlplanes,        fleet.hub.upbound.io
#                       spaces, *registrations
#   hub.upbound.io      realms                hub.upbound.io   (unchanged)
#   authentication.     identityproviders,    iam.hub.upbound.io
#                       users, groups
#   authorization.      *rolebindings,        iam.hub.upbound.io
#                       selfsubjectaccessreviews
#
# realms is why this cannot be a rename: hub.upbound.io still exists on 1.1.0
# and still serves it. Verified against a live 1.1.0 deployment.
#
# The index is built once per process and cached, so the /apis walk costs a
# handful of requests rather than one per lookup.
# ---------------------------------------------------------------------------

HUB_GV_CACHE=""

# Emit "resource<TAB>group<TAB>version" for every resource under a *.hub.upbound.io
# group. Subresources (a/b) are skipped: they are addressed through their parent.
hub_build_gv_index() {
  local dir="$1" groups_doc group versions version body
  groups_doc="$("$dir/hub-curl" /apis 2>/dev/null)" || return 1
  [ -n "$groups_doc" ] || return 1

  for group in $(jq -r '.groups[]?.name | select(endswith("hub.upbound.io"))' <<<"$groups_doc" 2>/dev/null); do
    # Preferred first, then the rest, so a deployment serving both an old and a
    # new version resolves to the one the server itself prefers.
    versions="$(jq -r --arg g "$group" '
      [.groups[] | select(.name == $g)][0]
      | [.preferredVersion.version] + [.versions[]?.version]
      | unique_by(.) | .[]' <<<"$groups_doc" 2>/dev/null)"
    for version in $versions; do
      case "$version" in ""|null) continue ;; esac
      body="$("$dir/hub-curl" "/apis/$group/$version" 2>/dev/null)" || continue
      jq -r --arg g "$group" --arg v "$version" '
        .resources[]? | select(.name | contains("/") | not)
        | "\(.name)\t\($g)\t\($v)"' <<<"$body" 2>/dev/null
    done
  done
}

# hub_resolve_gv <dir> <resource> [fallback_group] [fallback_version]
# Prints "group version". Falls back to the caller's pins when discovery fails,
# so the request returns the real error rather than one about /apis.
hub_resolve_gv() {
  local dir="$1" resource="$2" fb_group="${3:-}" fb_version="${4:-}" hit

  if [ -z "$HUB_GV_CACHE" ]; then
    HUB_GV_CACHE="$(hub_build_gv_index "$dir" 2>/dev/null)"
    # A single space marks "tried and got nothing", so a Hub that cannot be
    # reached is not re-walked on every lookup.
    [ -n "$HUB_GV_CACHE" ] || HUB_GV_CACHE=" "
  fi

  hit="$(printf '%s\n' "$HUB_GV_CACHE" | awk -F'\t' -v r="$resource" '$1 == r {print $2, $3; exit}')"
  if [ -n "$hit" ]; then
    printf '%s\n' "$hit"
    return 0
  fi

  if [ -n "$fb_group" ]; then
    printf '%s %s\n' "$fb_group" "$(hub_resolve_version "$dir" "$fb_group" "$fb_version")"
    return 0
  fi
  return 1
}

# hub_resolve_version <dir> <group> <pin>
#
# The pre-existing behaviour, kept for the fallback path: a group whose resource
# list could not be read still gets its version negotiated, so a pin the server
# does not serve is dropped rather than 404ing. The pin wins whenever the server
# serves it, because .preferredVersion is a different question - hub.upbound.io
# prefers v1alpha1, where Resource and ResourceStats are deprecated.
hub_resolve_version() {
  local dir="$1" group="$2" pin="$3" groups_doc resolved
  if groups_doc="$("$dir/hub-curl" /apis 2>/dev/null)"; then
    resolved="$(jq -r --arg g "$group" --arg pin "$pin" '
      [.groups[]? | select(.name == $g)] as $match
      | if ($match | length) == 0 then $pin
        elif ([$match[0].versions[]?.version] | index($pin)) != null then $pin
        else ($match[0].preferredVersion.version // $pin)
        end' <<<"$groups_doc" 2>/dev/null)" || resolved=""
    case "$resolved" in
      ""|null) ;;
      *) printf '%s\n' "$resolved"; return 0 ;;
    esac
  fi
  printf '%s\n' "$pin"
}
