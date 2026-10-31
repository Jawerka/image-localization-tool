#!/usr/bin/env bash
# Изолированный fake-root прогон bootstrap, update, rollback и health failure.

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

BIN="$WORK/bin"
UNIT_DIR="$WORK/systemd"
DEPLOY_ROOT="$WORK/install"
STATE="$WORK/systemctl-active"
LOG="$WORK/systemctl.log"
mkdir -p "$BIN" "$UNIT_DIR"

cat >"$BIN/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
action="$1"
shift
printf '%s %s\n' "$action" "$*" >>"$ILT_TEST_SYSTEMCTL_LOG"
case "$action" in
    start|restart) : >"$ILT_TEST_SYSTEMCTL_STATE" ;;
    stop) rm -f -- "$ILT_TEST_SYSTEMCTL_STATE" ;;
    is-active) [[ -f "$ILT_TEST_SYSTEMCTL_STATE" ]] ;;
esac
MOCK

cat >"$BIN/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
active="$(readlink -f -- "$ILT_TEST_ROOT/current" 2>/dev/null || true)"
if [[ -n "${ILT_TEST_FAIL_VERSION:-}" && "$(basename -- "$active")" == "$ILT_TEST_FAIL_VERSION" ]]; then
    printf '{"version":"dev","ready":false}\n'
else
    printf '{"version":"dev","ready":true}\n'
fi
MOCK

chmod +x "$BIN/systemctl" "$BIN/curl"

export PATH="$BIN:$PATH"
export ILT_DEPLOY_TEST_MODE=1
export ILT_TEST_UNIT_DIR="$UNIT_DIR"
export ILT_TEST_SYSTEMCTL="systemctl"
export ILT_TEST_SYSTEMCTL_STATE="$STATE"
export ILT_TEST_SYSTEMCTL_LOG="$LOG"
export ILT_TEST_ROOT="$DEPLOY_ROOT"
export ILT_HEALTH_TIMEOUT=1

make_bundle() {
    local version="$1"
    local folder="$WORK/bundle-$version"
    mkdir -p "$folder/_internal" "$folder/web"
    printf '#!/bin/sh\nexit 0\n' >"$folder/ImageLocalizationTool"
    chmod +x "$folder/ImageLocalizationTool"
    printf 'internal\n' >"$folder/_internal/runtime.dat"
    printf '<html></html>\n' >"$folder/web/index.html"
    cat >"$folder/release.json" <<EOF
{"schema":1,"version":"$version","platform":"linux-x64","executable":"ImageLocalizationTool"}
EOF
    cp "$ROOT_DIR/deploy/ilt.service" "$folder/ilt.service"
    printf '%s\n' "$folder"
}

assert_link_version() {
    local name="$1"
    local expected="$2"
    local actual
    actual="$(basename -- "$(readlink -f -- "$DEPLOY_ROOT/$name")")"
    [[ "$actual" == "$expected" ]] || {
        printf 'expected %s -> %s, got %s\n' "$name" "$expected" "$actual" >&2
        exit 1
    }
}

bundle_102="$(make_bundle 1.0.2)"
bash "$ROOT_DIR/scripts/install-server-linux.sh" --bundle "$bundle_102" --root "$DEPLOY_ROOT" --skip-components --health-timeout 1
assert_link_version current 1.0.2
[[ -L "$DEPLOY_ROOT/current/data" && -L "$DEPLOY_ROOT/current/models" && -L "$DEPLOY_ROOT/current/runtime" ]]
grep -F "ExecStart=$DEPLOY_ROOT/current/ImageLocalizationTool --headless --remote" "$UNIT_DIR/ilt.service" >/dev/null

printf 'preserve me\n' >"$DEPLOY_ROOT/shared/data/project.txt"
state_hash="$(sha256sum "$DEPLOY_ROOT/shared/data/project.txt" | cut -d ' ' -f 1)"
restart_count="$(grep -c '^restart ' "$LOG" || true)"
bash "$ROOT_DIR/scripts/install-server-linux.sh" --bundle "$bundle_102" --root "$DEPLOY_ROOT" --skip-components --health-timeout 1
[[ "$(grep -c '^restart ' "$LOG" || true)" == "$restart_count" ]]

bundle_103="$(make_bundle 1.0.3)"
bash "$ROOT_DIR/scripts/update-server-linux.sh" --bundle "$bundle_103" --root "$DEPLOY_ROOT" --health-timeout 1
assert_link_version current 1.0.3
assert_link_version previous 1.0.2

bash "$ROOT_DIR/scripts/rollback-server-linux.sh" --root "$DEPLOY_ROOT" --health-timeout 1
assert_link_version current 1.0.2
assert_link_version previous 1.0.3

bundle_104="$(make_bundle 1.0.4)"
export ILT_TEST_FAIL_VERSION=1.0.4
if bash "$ROOT_DIR/scripts/update-server-linux.sh" --bundle "$bundle_104" --root "$DEPLOY_ROOT" --health-timeout 1; then
    printf 'candidate with failed health unexpectedly activated\n' >&2
    exit 1
fi
unset ILT_TEST_FAIL_VERSION
assert_link_version current 1.0.2
assert_link_version previous 1.0.3
[[ "$(sha256sum "$DEPLOY_ROOT/shared/data/project.txt" | cut -d ' ' -f 1)" == "$state_hash" ]]

bundle_bad="$(make_bundle 1.0.5)"
printf '{not json\n' >"$bundle_bad/release.json"
if bash "$ROOT_DIR/scripts/update-server-linux.sh" --bundle "$bundle_bad" --root "$DEPLOY_ROOT" --health-timeout 1; then
    printf 'malformed release metadata unexpectedly passed validation\n' >&2
    exit 1
fi
assert_link_version current 1.0.2

if command -v flock >/dev/null 2>&1; then
    exec 8>"$DEPLOY_ROOT/.deployment.lock"
    flock -n 8
else
    mkdir "$DEPLOY_ROOT/.deployment.lock.test-lock"
fi
if bash "$ROOT_DIR/scripts/update-server-linux.sh" --bundle "$bundle_104" --root "$DEPLOY_ROOT" --health-timeout 1; then
    printf 'concurrent deployment unexpectedly acquired the lock\n' >&2
    exit 1
fi
if command -v flock >/dev/null 2>&1; then
    exec 8>&-
else
    rmdir "$DEPLOY_ROOT/.deployment.lock.test-lock"
fi

printf 'Linux deployment fake-root checks passed\n'
