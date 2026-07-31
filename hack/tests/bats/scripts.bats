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

@test "hub-list routes images to the catalog group" {
  run "$SKILL_DIR/scripts/hub-list" images
  [ "$status" -eq 0 ]
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
