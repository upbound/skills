#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0

load helper

setup() { setup_stubs; }
teardown() { teardown_stubs; }

# --- the security property -------------------------------------------------

@test "hub-curl keeps the token out of argv" {
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -eq 0 ]
  assert_token_never_in_argv
}

@test "hub-curl passes auth through a 0600 config file instead" {
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -eq 0 ]
  grep -q -- "--config" "$ARGV_LOG"
  [ -f "$STUB_DIR/curlrc-copy" ]
  grep -q "Authorization: Bearer" "$STUB_DIR/curlrc-copy"
  [ "$(cat "$STUB_DIR/curlrc-mode")" = "600" ]
}

@test "hub-curl leaves stdin free for a request body" {
  # hub-stats pipes JSON through hub-curl with --data-binary @-. If hub-curl
  # took stdin for its own config, the body would vanish silently.
  run "$SKILL_DIR/scripts/hub-stats" kind
  [ "$status" -eq 0 ]
  grep -q '"groupBy"' "$STUB_DIR/stdin.log"
}

@test "hub-curl removes the config file when it exits" {
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -eq 0 ]
  config_path="$(grep -o '\-\-config [^ ]*' "$ARGV_LOG" | head -1 | cut -d' ' -f2)"
  [ -n "$config_path" ]
  [ ! -f "$config_path" ]
}

@test "hub-list keeps the token out of argv" {
  run "$SKILL_DIR/scripts/hub-list" controlplanes
  [ "$status" -eq 0 ]
  assert_token_never_in_argv
}

@test "hub-kubectl keeps the token out of argv" {
  run "$SKILL_DIR/scripts/hub-kubectl" get controlplanes
  [ "$status" -eq 0 ]
  assert_token_never_in_argv
  grep -q -- "--token" "$ARGV_LOG" && return 1
  return 0
}

@test "hub-kubectl writes a 0600 kubeconfig" {
  run "$SKILL_DIR/scripts/hub-kubectl" get controlplanes
  [ "$status" -eq 0 ]
  [ -f "$STUB_DIR/kubeconfig-mode" ]
  [ "$(cat "$STUB_DIR/kubeconfig-mode")" = "600" ]
}

@test "hub-kubectl removes the kubeconfig when it exits" {
  run "$SKILL_DIR/scripts/hub-kubectl" get controlplanes
  [ "$status" -eq 0 ]
  config_path="$(grep -o 'KUBECONFIG=.*' "$ARGV_LOG" | head -1 | cut -d= -f2-)"
  [ -n "$config_path" ]
  [ ! -f "$config_path" ]
}

@test "hub-curl does not read the user's curlrc" {
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -eq 0 ]
  grep -q -- "--disable" "$ARGV_LOG"
}

# --- saying so when the answer is not what was asked for --------------------

@test "hub-list says a saturated count is not exact" {
  # metadata.total.count caps at 1000 and reports relation "gt" with no
  # magnitude, so reading count alone cannot tell 1,001 from 200,000.
  run "$SKILL_DIR/scripts/hub-list" resources 100 'saturate=1'
  [ "$status" -eq 0 ]
  [[ "$output" == *"more than 1000"* ]]
}

@test "hub-list stays quiet about an exact count" {
  run "$SKILL_DIR/scripts/hub-list" resources
  [ "$status" -eq 0 ]
  [[ "$output" != *"saturates"* ]]
}

@test "hub-stats reports a filter the server ignored" {
  # The stub drops "spaces", standing in for a server whose filter set has
  # drifted from this script's. The real handler drops unknown keys and returns
  # 200, so the whole fleet comes back looking like a filtered answer.
  run "$SKILL_DIR/scripts/hub-stats" kind -- spaces=insights-demo
  [ "$status" -eq 0 ]
  [[ "$output" == *"the server ignored these filters: spaces"* ]]
}

@test "hub-stats stays quiet when every filter was applied" {
  run "$SKILL_DIR/scripts/hub-stats" kind -- kinds=Bucket
  [ "$status" -eq 0 ]
  [[ "$output" != *"ignored these filters"* ]]
}

# --- hub-doctor ------------------------------------------------------------

@test "hub-doctor reports the endpoint and the versions each group serves" {
  run "$SKILL_DIR/scripts/hub-doctor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"https://hub.example.com"* ]]
  [[ "$output" == *"hub.upbound.io"* ]]
  [[ "$output" == *"v1beta1"* ]]
}

@test "hub-doctor names a group the deployment does not serve" {
  # catalog.hub.upbound.io is absent from the stub's discovery document, which
  # is what a feature gate being off looks like.
  run "$SKILL_DIR/scripts/hub-doctor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"images"* ]]
  [[ "$output" == *"feature gate off"* ]]
}

@test "hub-doctor names a resource served at other than its pinned version" {
  run "$SKILL_DIR/scripts/hub-doctor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"identityproviders"* ]]
  [[ "$output" == *"pinned v1, using v1beta1"* ]]
}

@test "hub-doctor fails clearly when HUB_API_URL is unset" {
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-doctor"
  [ "$status" -ne 0 ]
  [[ "$output" == *"HUB_API_URL"* ]]
}

# --- failing cleanly -------------------------------------------------------

@test "hub-curl fails clearly when HUB_API_URL is unset" {
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -ne 0 ]
  [[ "$output" == *"HUB_API_URL"* ]]
}

@test "hub-list fails clearly when HUB_API_URL is unset" {
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-list" controlplanes
  [ "$status" -ne 0 ]
  [[ "$output" == *"HUB_API_URL"* ]]
}

@test "hub-kubectl fails clearly when HUB_API_URL is unset" {
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-kubectl" get controlplanes
  [ "$status" -ne 0 ]
  [[ "$output" == *"HUB_API_URL"* ]]
}

@test "hub-curl names the fix when the credential helper is missing" {
  # The helper is downloaded, not committed, so a fresh checkout has none. Bash
  # would otherwise report exit 127 and a path, which is not a fix.
  rm -f "$SKILL_DIR/scripts/hub-credential-helper"
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -ne 0 ]
  [ "$status" -ne 127 ]
  [[ "$output" == *"hub-setup"* ]]
}

@test "hub-kubectl names the fix when the credential helper is missing" {
  rm -f "$SKILL_DIR/scripts/hub-credential-helper"
  run "$SKILL_DIR/scripts/hub-kubectl" get controlplanes
  [ "$status" -ne 0 ]
  [ "$status" -ne 127 ]
  [[ "$output" == *"hub-setup"* ]]
}

@test "hub-list with no arguments explains itself" {
  run "$SKILL_DIR/scripts/hub-list"
  [ "$status" -eq 2 ]
  [[ "$output" == *"hub-list"* ]]
}

# --- --help works offline, with no credentials -----------------------------

@test "every script supports --help without touching the network" {
  unset HUB_API_URL
  for script in "$SKILL_DIR"/scripts/hub-*; do
    case "$script" in
      # The downloaded binary, and sourced libraries which have no CLI.
      *hub-credential-helper | *.sh) continue ;;
    esac
    run "$script" --help
    [ "$status" -eq 0 ] || {
      echo "$(basename "$script") --help exited $status" >&2
      return 1
    }
    [ -n "$output" ]
  done
}

@test "--help prints the whole header comment and no source" {
  # Each script's help text is its own header comment. Extracting it with a
  # fixed line range drifts the moment anyone edits the header: too short cuts
  # the help mid-sentence, too long prints `set -euo pipefail` at the user.
  # Exit status alone cannot see either, so assert on the content.
  unset HUB_API_URL
  for script in "$SKILL_DIR"/scripts/hub-*; do
    case "$script" in
      *hub-credential-helper | *.sh) continue ;;
    esac
    name="$(basename "$script")"

    run "$script" --help
    [ "$status" -eq 0 ]

    if grep -qE '^(set -euo|dir=|usage\(\)|\. )' <<<"$output"; then
      echo "$name --help leaked shell source:" >&2
      grep -nE '^(set -euo|dir=|usage\(\)|\. )' <<<"$output" >&2
      return 1
    fi

    # Derived from the file independently of how the script does it, so a
    # hard-coded range that stops early fails here.
    header_last="$(awk 'NR>2 && !/^#/{exit}
                        NR>2{sub(/^# ?/, ""); if ($0 ~ /[^[:space:]]/) line=$0}
                        END{print line}' "$script")"
    help_last="$(grep -v '^[[:space:]]*$' <<<"$output" | tail -1)"
    [ "$help_last" = "$header_last" ] || {
      echo "$name --help does not reach the end of its header" >&2
      echo "  last help line:   $help_last" >&2
      echo "  last header line: $header_last" >&2
      return 1
    }
  done
}

# --- behavior --------------------------------------------------------------

@test "hub-list emits a JSON array when there are no items" {
  run "$SKILL_DIR/scripts/hub-list" controlplanes
  [ "$status" -eq 0 ]
  [ "$(echo "$output" | jq -r 'type')" = "array" ]
}

@test "hub-list passes extra arguments through as query parameters" {
  run "$SKILL_DIR/scripts/hub-list" resources 100 'ready=False' 'controlPlanes=prod-1'
  [ "$status" -eq 0 ]
  grep -q "ready=False" "$ARGV_LOG"
  grep -q "controlPlanes=prod-1" "$ARGV_LOG"
}

@test "hub-list routes identityproviders to the authentication group" {
  run "$SKILL_DIR/scripts/hub-list" identityproviders
  [ "$status" -eq 0 ]
  grep -q "authentication.hub.upbound.io" "$ARGV_LOG"
}

# --- version negotiation ---------------------------------------------------
#
# The stub's /apis serves authentication.hub.upbound.io at v1alpha1 and v1beta1
# but not v1, and hub.upbound.io at v1alpha1 and v1beta1 while preferring
# v1alpha1. Those two shapes are what these assert against.

@test "hub-list asks the server which version a group serves" {
  run "$SKILL_DIR/scripts/hub-list" identityproviders
  [ "$status" -eq 0 ]
  # The discovery request itself, not the /apis prefix every collection URL has.
  grep -qE "hub\.example\.com/apis( |$)" "$ARGV_LOG"
}

@test "hub-list drops a pinned version the server does not serve" {
  # The bug this replaced: identityproviders is pinned to v1, a Hub serving
  # only v1alpha1 and v1beta1 404s it, and asserting on the group alone did
  # not notice.
  run "$SKILL_DIR/scripts/hub-list" identityproviders
  [ "$status" -eq 0 ]
  grep -q "authentication.hub.upbound.io/v1beta1/identityproviders" "$ARGV_LOG"
  ! grep -q "authentication.hub.upbound.io/v1/identityproviders" "$ARGV_LOG"
}

@test "hub-list says so when it substitutes a version" {
  run "$SKILL_DIR/scripts/hub-list" identityproviders
  [ "$status" -eq 0 ]
  # bats folds stderr into $output unless --separate-stderr is used.
  [[ "$output" == *"does not serve v1"* ]]
}

@test "hub-list keeps its pin over the server's preferred version" {
  # hub.upbound.io serves v1beta1 and prefers v1alpha1, where Resource and
  # ResourceStats are deprecated. Following .preferredVersion would silently
  # downgrade every read.
  run "$SKILL_DIR/scripts/hub-list" resources
  [ "$status" -eq 0 ]
  grep -q "hub.upbound.io/v1beta1/resources" "$ARGV_LOG"
  ! grep -q "hub.upbound.io/v1alpha1/resources" "$ARGV_LOG"
}

@test "hub-list falls back to the pin when discovery gives nothing usable" {
  # catalog.hub.upbound.io is absent from the stub's /apis, as it is from a
  # deployment with the gate off. The request is still built with the pin, and
  # the server is left to report the 404 -- guessing a version for a group that
  # is not served would only turn one clear error into a confusing one.
  run "$SKILL_DIR/scripts/hub-list" images
  [ "$status" -ne 0 ]
  grep -q "catalog.hub.upbound.io/v1alpha1/images" "$ARGV_LOG"
  [[ "$output" == *"404"* ]]
}

@test "hub-list routes images to the catalog group" {
  # Exits non-zero because the stub serves no catalog group; the assertion here
  # is the routing, which happens before the request.
  run "$SKILL_DIR/scripts/hub-list" images
  grep -q "catalog.hub.upbound.io" "$ARGV_LOG"
}

@test "hub-stats builds a resourcestats query body" {
  run "$SKILL_DIR/scripts/hub-stats" kind controlPlane -- ready=False controlPlanes=a,b
  [ "$status" -eq 0 ]
  body="$(cat "$STUB_DIR/stdin.log" | grep -o '{.*}' | tail -1)"
  [ "$(echo "$body" | jq -r '.query.groupBy | join(",")')" = "kind,controlPlane" ]
  [ "$(echo "$body" | jq -r '.query.filters.ready')" = "False" ]
  [ "$(echo "$body" | jq -r '.query.filters.controlPlanes | join(",")')" = "a,b" ]
}

@test "hub-stats rejects a filter that is not key=value" {
  run "$SKILL_DIR/scripts/hub-stats" kind -- notavalidfilter
  [ "$status" -eq 2 ]
}

# --- the agent drives setup, the user does not ------------------------------

@test "hub-setup exits 3 when no endpoint is configured" {
  # 3 is the signal for "ask the user", distinct from 1 for a real failure.
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-setup"
  [ "$status" -eq 3 ]
  [[ "$output" == *"Ask the user"* ]]
}

@test "hub-setup saves the endpoint so it is asked for only once" {
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-setup" --url https://saved.example.com
  config="$XDG_CONFIG_HOME/upbound/hub.env"
  [ -f "$config" ]
  grep -q '^HUB_API_URL=https://saved.example.com$' "$config"
}

@test "hub-setup rejects a value that is not a URL" {
  unset HUB_API_URL
  run "$SKILL_DIR/scripts/hub-setup" --url not-a-url
  [ "$status" -eq 1 ]
  [[ "$output" == *"must be a URL"* ]]
}

@test "saving twice replaces rather than appends" {
  unset HUB_API_URL
  "$SKILL_DIR/scripts/hub-setup" --url https://one.example.com >/dev/null 2>&1 || true
  "$SKILL_DIR/scripts/hub-setup" --url https://two.example.com >/dev/null 2>&1 || true
  config="$XDG_CONFIG_HOME/upbound/hub.env"
  [ "$(grep -c '^HUB_API_URL=' "$config")" -eq 1 ]
  grep -q '^HUB_API_URL=https://two.example.com$' "$config"
}

@test "the saved endpoint is picked up with no environment variable" {
  unset HUB_API_URL
  "$SKILL_DIR/scripts/hub-setup" --url https://saved.example.com >/dev/null 2>&1 || true
  run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -eq 0 ]
  grep -q "https://saved.example.com/apis" "$ARGV_LOG"
}

@test "HUB_API_URL in the environment overrides the saved endpoint" {
  "$SKILL_DIR/scripts/hub-setup" --url https://saved.example.com >/dev/null 2>&1 || true
  HUB_API_URL="https://override.example.com" run "$SKILL_DIR/scripts/hub-curl" /apis
  [ "$status" -eq 0 ]
  grep -q "https://override.example.com/apis" "$ARGV_LOG"
}
