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
# Hub 1.1.0 split the API surface that 1.0.x served from one group, so pinning a
# group in the caller builds a wrong URL against one major or the other:
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
# realms is why this cannot be a rename: hub.upbound.io still exists on 1.1.0 and
# still serves it.
#
# The caller's pin is a PREFERENCE, not just a fallback. It is probed first, so a
# 1.0.x Hub that serves the resource at the pinned version keeps it. That matters
# because hub.upbound.io serves v1alpha1, v1alpha2 and v1beta1 while PREFERRING
# v1alpha1, where Resource and ResourceStats are deprecated - following
# .preferredVersion would silently downgrade every read.
#
# Probing in preference order also keeps discovery cheap: the pinned group and
# version are usually right, so the common case is /apis plus one probe rather
# than a walk of every group at every version.
# ---------------------------------------------------------------------------

HUB_APIS_DOC=""       # cached /apis
HUB_GV_PROBES=""      # cached "group/version<TAB>resource resource ..." lines

# Cached GET of /apis. One space means "tried and failed", so an unreachable Hub
# is not re-requested on every lookup.
hub_apis_doc() {
  local dir="$1"
  if [ -z "$HUB_APIS_DOC" ]; then
    HUB_APIS_DOC="$("$dir/hub-curl" /apis 2>/dev/null)" || HUB_APIS_DOC=" "
    [ -n "$HUB_APIS_DOC" ] || HUB_APIS_DOC=" "
  fi
  case "$HUB_APIS_DOC" in " ") return 1 ;; esac
  printf '%s' "$HUB_APIS_DOC"
}

# Does <group>/<version> serve <resource>? Cached per group/version.
hub_gv_serves() {
  local dir="$1" gv="$2" resource="$3" body names cached
  cached="$(printf '%s\n' "$HUB_GV_PROBES" | awk -F'\t' -v k="$gv" '$1 == k {print $2; found=1} END {if (!found) print "\x01"}')"
  if [ "$cached" = $'\x01' ]; then
    body="$("$dir/hub-curl" "/apis/$gv" 2>/dev/null)" || body=""
    names="$(printf '%s' "$body" | jq -r '[.resources[]? | select(.name | contains("/") | not) | .name] | join(" ")' 2>/dev/null)" || names=""
    HUB_GV_PROBES="$(printf '%s\n%s\t%s' "$HUB_GV_PROBES" "$gv" "$names")"
    cached="$names"
  fi
  case " $cached " in *" $resource "*) return 0 ;; esac
  return 1
}

# hub_pin_fallback <apis> <group> <pin>
#
# Version negotiation for the path where no group's resource list could be read.
# The pin wins when the server serves it; otherwise the server's preferred
# version. Without this a Hub that lists groups but whose per-group documents are
# unreachable keeps a pinned version the server does not serve, and 404s.
hub_pin_fallback() {
  local apis="$1" group="$2" pin="$3" resolved
  resolved="$(printf '%s' "$apis" | jq -r --arg g "$group" --arg pin "$pin" '
    [.groups[]? | select(.name == $g)] as $match
    | if ($match | length) == 0 then $pin
      elif ([$match[0].versions[]?.version] | index($pin)) != null then $pin
      else ($match[0].preferredVersion.version // $pin)
      end' 2>/dev/null)" || resolved=""
  case "$resolved" in ""|null) printf '%s\n' "$pin" ;; *) printf '%s\n' "$resolved" ;; esac
}

# hub_resolve_gv <dir> <resource> [pin_group] [pin_version]
#
# Prints "group version". Probes the pinned group/version first, then the rest of
# the pinned group's versions, then every other *.hub.upbound.io group. Falls
# back to the pin unchanged when discovery fails, so the caller's request returns
# the real error rather than one about /apis.
hub_resolve_gv() {
  local dir="$1" resource="$2" pin_group="${3:-}" pin_version="${4:-}"
  local apis groups group versions version

  if ! apis="$(hub_apis_doc "$dir")"; then
    [ -n "$pin_group" ] && { printf '%s %s\n' "$pin_group" "$pin_version"; return 0; }
    return 1
  fi

  # Probe order: the caller's pin, then the groups most likely to serve a
  # listable resource, then whatever else the server reports. This is a HINT
  # only - an unknown or reordered group still resolves, it just costs one more
  # request. ingest. is last because it is the connector's write path and serves
  # nothing anyone lists.
  groups="$(printf '%s' "$apis" | jq -r --arg pin "$pin_group" '
    ["inventory.hub.upbound.io","fleet.hub.upbound.io","iam.hub.upbound.io",
     "hub.upbound.io","catalog.hub.upbound.io","registry.hub.upbound.io",
     "agent.hub.upbound.io","ingest.hub.upbound.io"] as $pref
    | [.groups[]?.name | select(endswith("hub.upbound.io"))] as $all
    | ($all | map(select(. == $pin))) as $first
    | ($all | map(select(. != $pin))) as $rest
    | ($first
       + ($pref | map(select(. as $g | $rest | index($g))))
       + ($rest | map(select(. as $g | $pref | index($g) | not))))
    | .[]' 2>/dev/null)"

  for group in $groups; do
    # Pinned version first, then the server's preferred, then the rest. reduce
    # rather than unique_by, because unique_by SORTS - and an alphabetical sort
    # puts the deprecated v1alpha1 ahead of v1beta1.
    versions="$(printf '%s' "$apis" | jq -r --arg g "$group" --arg pin "$pin_version" '
      [.groups[] | select(.name == $g)][0] as $m
      | ([$pin] + [$m.preferredVersion.version] + [$m.versions[]?.version])
      | map(select(. != null and . != ""))
      | reduce .[] as $v ([]; if index([$v]) then . else . + [$v] end)
      | map(select(. as $v | [$m.versions[]?.version] | index($v)))
      | .[]' 2>/dev/null)"
    for version in $versions; do
      if hub_gv_serves "$dir" "$group/$version" "$resource"; then
        printf '%s %s\n' "$group" "$version"
        return 0
      fi
    done
  done

  [ -n "$pin_group" ] && {
    printf '%s %s\n' "$pin_group" "$(hub_pin_fallback "$apis" "$pin_group" "$pin_version")"
    return 0
  }
  return 1
}
