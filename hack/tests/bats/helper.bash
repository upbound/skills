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
body='{"items":[],"metadata":{"total":{"count":0,"relation":"eq"}}}'
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
