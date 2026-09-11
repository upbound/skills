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

  cat > "$STUB_DIR/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >> "$ARGV_LOG"
# Keep a copy of the auth config, and its mode, so both can be asserted after
# the script's trap has cleaned it up.
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
case " \$* " in
  *" --data-binary @- "*) cat >> "$STUB_DIR/stdin.log" ;;
esac
out=""
prev=""
for a in "\$@"; do
  if [ "\$prev" = "-o" ]; then out="\$a"; fi
  prev="\$a"
done
# /apis is discovery, not a collection. hub-list reads it to find which
# version a group actually serves, so answering it with an item list would
# make every lookup fall back to its pinned version and prove nothing.
#
# hub.upbound.io deliberately prefers v1alpha1 while also serving v1beta1:
# that is what shows the pin winning over .preferredVersion. The
# authentication group deliberately omits v1, which is what the pin gets
# wrong on a real deployment.
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
# Opt-in 1.1.0 surface: set HUB_STUB_SHAPE=1.1.0 in a test. Group names match a
# live 1.1.0 deployment, where hub.upbound.io survives but serves only realms.
if [ "\${HUB_STUB_SHAPE:-1.0.x}" = "1.1.0" ]; then
  discovery='{"kind":"APIGroupList","groups":[
    {"name":"hub.upbound.io","versions":[{"version":"v1beta1"}],
     "preferredVersion":{"version":"v1beta1"}},
    {"name":"inventory.hub.upbound.io","versions":[{"version":"v1beta1"}],
     "preferredVersion":{"version":"v1beta1"}},
    {"name":"fleet.hub.upbound.io","versions":[{"version":"v1beta1"}],
     "preferredVersion":{"version":"v1beta1"}},
    {"name":"iam.hub.upbound.io","versions":[{"version":"v1beta1"}],
     "preferredVersion":{"version":"v1beta1"}}
  ]}'
fi
# Per-group resource lists, which is what makes the group-resolution path
# testable. Without these the probe always misses and every lookup silently
# exercises the pinned fallback instead - which is how a version downgrade
# slipped past this suite once.
#
# This is the 1.0.x layout: hub.upbound.io carries the inventory and fleet
# resources that 1.1.0 moves out to inventory./fleet.
hub_resources='"resources","resourcestats","lenses","typedefinitions","crossplanepackages","resourcerelationships","resourcerelationshiptrees","controlplanes","spaces","realms"'
authn_resources='"identityproviders","users","groups"'
authz_resources='"organizationrolebindings","realmrolebindings","selfsubjectaccessreviews"'
mk_list() {
  printf '{"kind":"APIResourceList","resources":['
  first=1
  for n in \$(printf '%s' "\$1" | tr ',' ' ' | tr -d '"'); do
    [ \$first -eq 1 ] || printf ','
    printf '{"name":"%s","namespaced":false,"verbs":["get","list"]}' "\$n"
    first=0
  done
  printf ']}'
}
# Pick out the request URL and reduce it to a path, so a group-version
# discovery request (/apis/g/v) can be told apart from a collection under it
# (/apis/g/v/resources). Matching on a substring would answer both with the
# same body and quietly break one of them.
url=""
for a in "\$@"; do
  case "\$a" in https://*|http://*) url="\$a" ;; esac
done
path="\${url#*://}"; path="/\${path#*/}"; path="\${path%%\\?*}"; path="\${path%/}"

if [ "\${HUB_STUB_SHAPE:-1.0.x}" = "1.1.0" ]; then
  hub_resources='"realms"'
  inventory_resources='"resources","resourcestats","lenses","typedefinitions","crossplanepackages","resourcerelationships","resourcerelationshiptrees"'
  fleet_resources='"controlplanes","spaces","controlplaneregistrations","spaceregistrations"'
  iam_resources='"identityproviders","users","groups","organizationrolebindings","realmrolebindings","selfsubjectaccessreviews"'
fi
body='{"items":[],"metadata":{"total":{"count":0,"relation":"eq"}}}'
case "\$path" in
  /apis) body="\$discovery" ;;
  /apis/*/*/*) : ;;                       # collection: keep the item list
  /apis/hub.upbound.io/*)                 body="\$(mk_list "\$hub_resources")" ;;
  /apis/authentication.hub.upbound.io/*)  body="\$(mk_list "\$authn_resources")" ;;
  /apis/authorization.hub.upbound.io/*)   body="\$(mk_list "\$authz_resources")" ;;
  /apis/inventory.hub.upbound.io/*)       body="\$(mk_list "\$inventory_resources")" ;;
  /apis/fleet.hub.upbound.io/*)           body="\$(mk_list "\$fleet_resources")" ;;
  /apis/iam.hub.upbound.io/*)             body="\$(mk_list "\$iam_resources")" ;;
esac
if [ -n "\$out" ]; then printf '%s' "\$body" > "\$out"; else printf '%s' "\$body"; fi
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
