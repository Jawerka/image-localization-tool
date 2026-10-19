#!/usr/bin/env bash
# Общие проверки и операции для установки, обновления и отката Linux-сервера.

set -Eeuo pipefail

ILT_DEFAULT_ROOT="/opt/image-localization-tool"
ILT_SERVICE_NAME="ilt.service"
ILT_HEALTH_URL="${ILT_HEALTH_URL:-http://127.0.0.1:8765/v1/health}"
ILT_HEALTH_TIMEOUT="${ILT_HEALTH_TIMEOUT:-60}"
ILT_DEPLOY_TEST_MODE="${ILT_DEPLOY_TEST_MODE:-0}"
ILT_ROOT="${ILT_ROOT:-$ILT_DEFAULT_ROOT}"
ILT_RELEASES="${ILT_ROOT}/releases"
ILT_SHARED="${ILT_ROOT}/shared"
ILT_LOCK_FILE="${ILT_ROOT}/.deployment.lock"

ilt_die() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

ilt_info() {
    printf '%s\n' "$*"
}

ilt_require_root() {
    if [[ "$ILT_DEPLOY_TEST_MODE" == "1" ]]; then
        return
    fi
    [[ "$(id -u)" -eq 0 ]] || ilt_die "запустите команду через sudo"
}

ilt_require_commands() {
    local command_name
    for command_name in "$@"; do
        command -v "$command_name" >/dev/null 2>&1 || ilt_die "не найдена команда: $command_name"
    done
}

ilt_validate_root() {
    [[ "$ILT_ROOT" == /* && "$ILT_ROOT" != "/" ]] || ilt_die "корень установки должен быть абсолютным и не равным /"
    [[ "$ILT_ROOT" =~ ^/[A-Za-z0-9/._-]+$ ]] || ilt_die "путь установки может содержать только латинские буквы, цифры, / . _ и -"
    [[ "$ILT_HEALTH_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || ilt_die "health timeout должен быть положительным числом секунд"
    if [[ "$ILT_DEPLOY_TEST_MODE" == "1" ]]; then
        [[ -n "${ILT_TEST_UNIT_DIR:-}" ]] || ilt_die "ILT_TEST_UNIT_DIR обязателен в test mode"
        ILT_UNIT_DIR="$ILT_TEST_UNIT_DIR"
    else
        ILT_UNIT_DIR="${ILT_UNIT_DIR:-/etc/systemd/system}"
    fi
}

ilt_systemctl() {
    if [[ "$ILT_DEPLOY_TEST_MODE" == "1" && -n "${ILT_TEST_SYSTEMCTL:-}" ]]; then
        "$ILT_TEST_SYSTEMCTL" "$@"
    else
        systemctl "$@"
    fi
}

ilt_release_fields() {
    local directory="$1"
    local metadata="$directory/release.json"
    [[ -f "$metadata" ]] || ilt_die "в $directory нет release.json"
    python3 -c 'import json,re,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); version=str(value.get("version", "")) if isinstance(value, dict) else ""; valid=isinstance(value,dict) and value.get("schema")==1 and value.get("platform")=="linux-x64" and value.get("executable")=="ImageLocalizationTool" and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}",version); sys.exit("invalid Linux release metadata") if not valid else print(version)' "$metadata"
}

ilt_validate_release() {
    local directory="$1"
    local expected_version="${2:-}"
    local version
    [[ -d "$directory" ]] || ilt_die "каталог релиза не найден: $directory"
    [[ ! -L "$directory" ]] || ilt_die "каталог релиза не должен быть symlink: $directory"
    version="$(ilt_release_fields "$directory")" || ilt_die "не удалось проверить release.json в $directory"
    [[ ! -L "$directory/ImageLocalizationTool" && ! -L "$directory/_internal" && ! -L "$directory/web" ]] || ilt_die "файлы релиза не должны быть symlink"
    [[ -x "$directory/ImageLocalizationTool" ]] || ilt_die "нет исполняемого ImageLocalizationTool в $directory"
    [[ -d "$directory/_internal" && -d "$directory/web" ]] || ilt_die "в релизе отсутствуют _internal или web"
    if [[ -n "$expected_version" && "$version" != "$expected_version" ]]; then
        ilt_die "версия релиза $version не совпадает с каталогом $expected_version"
    fi
    printf '%s\n' "$version"
}

ilt_bundle_to_release() {
    local bundle="$1"
    local destination="$2"
    local version
    version="$(ilt_validate_release "$bundle")"
    if [[ -e "$destination" ]]; then
        [[ ! -L "$destination" ]] || ilt_die "каталог релиза не должен быть symlink: $destination"
        ilt_validate_release "$destination" "$version" >/dev/null || ilt_die "каталог назначения уже существует и невалиден: $destination"
        return 0
    fi

    local stage
    stage="$(mktemp -d "$ILT_RELEASES/.staging-${version}.XXXXXX")"
    if ! cp -a "$bundle/ImageLocalizationTool" "$bundle/_internal" "$bundle/web" "$bundle/release.json" "$stage/"; then
        rm -rf -- "$stage"
        ilt_die "не удалось скопировать файлы релиза"
    fi
    if [[ -d "$bundle/fonts" ]]; then
        cp -a "$bundle/fonts" "$stage/"
    fi
    for folder in data models runtime; do
        ln -s "$ILT_SHARED/$folder" "$stage/$folder"
    done
    chmod 0755 "$stage"
    ilt_validate_release "$stage" "$version" >/dev/null || {
        rm -rf -- "$stage"
        ilt_die "сборка staged-каталога не прошла проверку"
    }
    mv -- "$stage" "$destination" || {
        rm -rf -- "$stage"
        ilt_die "не удалось активировать каталог версии $version"
    }
}

ilt_atomic_link() {
    local target="$1"
    local link="$2"
    local temp="${link}.new.$$"
    [[ ! -e "$link" || -L "$link" ]] || ilt_die "отказ заменять не symlink: $link"
    rm -f -- "$temp"
    ln -s -- "$target" "$temp"
    mv -Tf -- "$temp" "$link"
}

ilt_current_release() {
    [[ -L "$ILT_ROOT/current" ]] || ilt_die "нет active release в $ILT_ROOT/current"
    local target
    target="$(readlink -f -- "$ILT_ROOT/current")"
    [[ "$target" == "$ILT_RELEASES/"* && -d "$target" ]] || ilt_die "active release находится за пределами releases/"
    ilt_validate_release "$target" "$(basename -- "$target")" >/dev/null
    printf '%s\n' "$target"
}

ilt_install_unit() {
    local template="$1"
    local target="$ILT_UNIT_DIR/$ILT_SERVICE_NAME"
    local temporary
    temporary="$(mktemp "$ILT_UNIT_DIR/.ilt.service.XXXXXX")"
    sed "s|@ILT_ROOT@|$ILT_ROOT|g" "$template" >"$temporary"
    chmod 0644 "$temporary"
    local changed=1
    if [[ -f "$target" ]] && cmp -s -- "$temporary" "$target"; then
        changed=0
        rm -f -- "$temporary"
    else
        mv -- "$temporary" "$target"
    fi
    printf '%s\n' "$changed"
}

ilt_health_ready() {
    local body
    body="$(curl --silent --show-error --fail --max-time 3 "$ILT_HEALTH_URL" 2>/dev/null)" || return 1
    python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if isinstance(d,dict) and d.get("ready") is True else 1)' "$body" >/dev/null 2>&1
}

ilt_wait_health() {
    local deadline=$((SECONDS + ILT_HEALTH_TIMEOUT))
    while (( SECONDS <= deadline )); do
        if ilt_health_ready; then
            return 0
        fi
        sleep 1
    done
    return 1
}

ilt_start_and_check() {
    local action="$1"
    ilt_systemctl "$action" "$ILT_SERVICE_NAME" || return 1
    ilt_wait_health
}

ilt_prepare_layout() {
    mkdir -p "$ILT_RELEASES" "$ILT_SHARED/data" "$ILT_SHARED/models" "$ILT_SHARED/runtime" "$ILT_UNIT_DIR"
    [[ ! -L "$ILT_RELEASES" && ! -L "$ILT_SHARED" ]] || ilt_die "releases/ и shared/ должны быть обычными каталогами"
    if [[ "$ILT_DEPLOY_TEST_MODE" != "1" ]]; then
        if ! getent group ilt >/dev/null 2>&1; then
            groupadd --system ilt
        fi
        if ! getent passwd ilt >/dev/null 2>&1; then
            useradd --system --gid ilt --home-dir "$ILT_SHARED/data" --no-create-home --shell /usr/sbin/nologin ilt
        fi
        if [[ ! -f "$ILT_SHARED/.ownership-ready" ]]; then
            chown -R ilt:ilt "$ILT_SHARED"
            touch "$ILT_SHARED/.ownership-ready"
            chown ilt:ilt "$ILT_SHARED/.ownership-ready"
        else
            chown ilt:ilt "$ILT_SHARED" "$ILT_SHARED/data" "$ILT_SHARED/models" "$ILT_SHARED/runtime"
        fi
        chown root:ilt "$ILT_ROOT" "$ILT_RELEASES"
        chmod 0750 "$ILT_ROOT" "$ILT_RELEASES" "$ILT_SHARED"
    fi
}

ilt_prepare_components() {
    local release="$1"
    if [[ "$ILT_DEPLOY_TEST_MODE" == "1" ]]; then
        return 0
    fi
    runuser -u ilt -- env \
        "ILT_INSTALL_ROOT=$release" \
        "ILT_DATA_DIR=$ILT_SHARED/data" \
        "ILT_COMPONENT_ROOT=$ILT_SHARED" \
        "$release/ImageLocalizationTool" --deploy all
}

ilt_acquire_lock() {
    mkdir -p "$ILT_ROOT"
    exec 9>"$ILT_LOCK_FILE"
    if [[ "$ILT_DEPLOY_TEST_MODE" == "1" ]] && ! command -v flock >/dev/null 2>&1; then
        local fallback_lock="${ILT_LOCK_FILE}.test-lock"
        mkdir -- "$fallback_lock" 2>/dev/null || ilt_die "другая установка или обновление уже выполняется"
        trap 'rmdir -- "${ILT_LOCK_FILE}.test-lock" 2>/dev/null || true' EXIT
        return
    fi
    command -v flock >/dev/null 2>&1 || ilt_die "не найдена команда: flock"
    flock -n 9 || ilt_die "другая установка или обновление уже выполняется"
}
