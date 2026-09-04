# SPDX-License-Identifier: Apache-2.0
#
# Puts fake curl, kubectl, jq-adjacent and credential-helper binaries earlier on
# PATH so the scripts can be exercised with no network and no credentials.
#
# Each stub records the argv it was called with, which is what lets us assert the
# thing that matters: a bearer token must never appear in a command argument,
# because anything on a command line is readable by every process via ps.

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../skills/upbound-hub" && pwd)"
FAKE_TOKEN="eyJfaWQiOiJ0ZXN0LXRva2VuLXZhbHVlIn0.signature"

setup_stubs() {
  STUB_DIR="$(mktemp -d)"
  ARGV_LOG="$STUB_DIR/argv.log"
  : > "$ARGV_LOG"

  # Scripts resolve the helper from their own directory, so the stub has to go
  # there -- which means a real one installed by hub-setup is in the way. Move it
  # aside instead of clobbering it: teardown deletes the stub, and deleting a
  # 31 MB binary costs the user a re-download and possibly a fresh sign-in.
  #
  # A rename within the same directory, so it is atomic and moves no bytes. Dot
  # prefixed because validate.py skips dotfiles, and an interrupted run leaves
  # this behind.
  HELPER="$SKILL_DIR/scripts/hub-credential-helper"
  HELPER_BACKUP="$SKILL_DIR/scripts/.hub-credential-helper.bats-backup"
  if [ -e "$HELPER" ]; then
    mv "$HELPER" "$HELPER_BACKUP"
  fi

  cat > "$HELPER" <<EOF
#!/usr/bin/env bash
echo "hub-credential-helper \$*" >> "$ARGV_LOG"
case "\$1" in
  get-token) printf '%s' "$FAKE_TOKEN" ;;
  login)     echo "logged in" >&2 ;;
esac
EOF
  chmod +x "$HELPER"

  # The stub answers only what the discovery document below advertises, and
  # 404s everything else the way the server would. A stub that says yes to every
  # path is how two real bugs shipped with passing tests: hub-curl aborting on
  # bash 3.2, and hub-list requesting a version the server does not serve. The
  # test harness should not be more permissive than the thing it stands in for.
  #
  # hub.upbound.io deliberately prefers v1alpha1 while also serving v1beta1:
  # that is what shows a pinned version winning over .preferredVersion. The
  # authentication group deliberately omits v1, which is what the pin gets wrong
  # on a real deployment. catalog.hub.upbound.io is absent entirely, standing in
  # for a feature gate that is off.
  cat > "$STUB_DIR/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >> "$ARGV_LOG"
prev=""
for a in "\$@"; do
  if [ "\$prev" = "--config" ] && [ -f "\$a" ]; then
    cp "\$a" "$STUB_DIR/curlrc-copy"
    stat -f '%Lp' "\$a" > "$STUB_DIR/curlrc-mode" 2>/dev/null \
      || stat -c '%a' "\$a" > "$STUB_DIR/curlrc-mode"
  fi
  prev="\$a"
done
# Read stdin only when a body is actually being sent. Testing \`[ ! -t 0 ]\`
# instead would block forever whenever stdin is an unclosed inherited pipe,
# which is how this stub is invoked outside bats.
sent_body=""
case " \$* " in
  *" --data-binary @- "*) sent_body="\$(cat)"; printf '%s' "\$sent_body" >> "$STUB_DIR/stdin.log" ;;
esac
out=""
url=""
prev=""
for a in "\$@"; do
  if [ "\$prev" = "-o" ]; then out="\$a"; fi
  case "\$a" in https://*|http://*) url="\$a" ;; esac
  prev="\$a"
done

discovery='{"kind":"APIGroupList","groups":[
  {"name":"hub.upbound.io",
   "versions":[{"version":"v1alpha1"},{"version":"v1beta1"}],
   "preferredVersion":{"version":"v1alpha1"}},
  {"name":"authentication.hub.upbound.io",
   "versions":[{"version":"v1alpha1"},{"version":"v1beta1"}],
   "preferredVersion":{"version":"v1beta1"}},
  {"name":"authorization.hub.upbound.io",
   "versions":[{"version":"v1beta1"}],
   "preferredVersion":{"version":"v1beta1"}}
]}'
items='{"items":[],"metadata":{"total":{"count":0,"relation":"eq"}}}'
# Opt-in via a query parameter, so only the test that wants a saturated count
# gets one: metadata.total.count caps at 1000 and then reports relation "gt".
case "\$url" in
  *saturate=1*) items='{"items":[],"metadata":{"total":{"count":1000,"relation":"gt"}}}' ;;
esac

# The path, with any query string removed.
path="\${url#*://}"; path="/\${path#*/}"; path="\${path%%\\?*}"

emit() {
  if [ -n "\$out" ]; then printf '%s' "\$1" > "\$out"; else printf '%s' "\$1"; fi
}
not_found() {
  # --fail-with-body: curl writes the body and still exits 22.
  emit '{"kind":"Status","apiVersion":"v1","status":"Failure","message":"404 page not found","reason":"NotFound","code":404}'
  exit 22
}

case "\$path" in
  /apis|/apis/) emit "\$discovery"; exit 0 ;;
esac

# Everything else must name a group and version the discovery document serves.
gv="\$(printf '%s' "\$path" | awk -F/ 'NF>3 {print \$3 "/" \$4}')"
case "\$gv" in
  hub.upbound.io/v1alpha1|hub.upbound.io/v1beta1) ;;
  authentication.hub.upbound.io/v1alpha1|authentication.hub.upbound.io/v1beta1) ;;
  authorization.hub.upbound.io/v1beta1) ;;
  *) not_found ;;
esac

case "\$path" in
  */resourcestats)
    # Echo back the filters that were applied, dropping the ones this server
    # does not know -- which is exactly what the real handler does, silently.
    # 'spaces' is treated as unknown here to stand in for a server whose filter
    # set has drifted from the client's.
    emit "\$(printf '%s' "\$sent_body" | jq -c '
      {kind: "ResourceStats", apiVersion: "hub.upbound.io/v1beta1",
       query: {filters: ((.query.filters // {}) | with_entries(select(.key |
                 IN("kinds","groups","controlPlanes","realms","ready","synced","healthy")))),
               groupBy: (.query.groupBy // [])},
       results: {summary: {totalCount: 0, readyTrue: 0, readyFalse: 0, readyUnknown: 0},
                 groups: []}}')"
    exit 0 ;;
esac

emit "\$items"
EOF
  chmod +x "$STUB_DIR/curl"

  cat > "$STUB_DIR/kubectl" <<EOF
#!/usr/bin/env bash
echo "kubectl \$*" >> "$ARGV_LOG"
echo "KUBECONFIG=\${KUBECONFIG:-unset}" >> "$ARGV_LOG"
if [ -n "\${KUBECONFIG:-}" ] && [ -f "\$KUBECONFIG" ]; then
  cp "\$KUBECONFIG" "$STUB_DIR/seen-kubeconfig"
  stat -f '%Lp' "\$KUBECONFIG" > "$STUB_DIR/kubeconfig-mode" 2>/dev/null \
    || stat -c '%a' "\$KUBECONFIG" > "$STUB_DIR/kubeconfig-mode"
fi
EOF
  chmod +x "$STUB_DIR/kubectl"

  PATH="$STUB_DIR:$PATH"
  export PATH
  export HUB_API_URL="https://hub.example.com"
  # Isolated, so a real ~/.config/upbound/hub.env cannot leak into a test and
  # make an unconfigured case look configured.
  export XDG_CONFIG_HOME="$STUB_DIR/config"
}

teardown_stubs() {
  local helper="$SKILL_DIR/scripts/hub-credential-helper"
  local backup="$SKILL_DIR/scripts/.hub-credential-helper.bats-backup"
  rm -f "$helper"
  if [ -e "$backup" ]; then
    mv "$backup" "$helper"
  fi
  rm -rf "$STUB_DIR"
}

# The whole point of the stubs.
assert_token_never_in_argv() {
  if grep -q -- "$FAKE_TOKEN" "$ARGV_LOG"; then
    echo "FAIL: the bearer token appeared in a command argument:" >&2
    grep -- "$FAKE_TOKEN" "$ARGV_LOG" >&2
    return 1
  fi
}
