#!/usr/bin/env bash
# Переключить сервис на сохранённый previous release и проверить его готовность.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/linux-deploy-common.sh
source "$SCRIPT_DIR/linux-deploy-common.sh"

usage() {
    cat <<'EOF'
Использование: sudo rollback-server-linux.sh [--root PATH] [--health-timeout SECONDS]

Переключает current и previous между двумя сохранёнными версиями. Данные не удаляются.
EOF
}

while (($#)); do
    case "$1" in
        --root) (($# >= 2)) || ilt_die "для --root нужен путь"; ILT_ROOT="$2"; ILT_RELEASES="$ILT_ROOT/releases"; ILT_SHARED="$ILT_ROOT/shared"; ILT_LOCK_FILE="$ILT_ROOT/.deployment.lock"; shift 2 ;;
        --health-timeout) (($# >= 2)) || ilt_die "для --health-timeout нужны секунды"; ILT_HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) ilt_die "неизвестный аргумент: $1" ;;
    esac
done

ilt_require_root
ilt_validate_root
ilt_require_commands id python3 mkdir mv rm ln readlink curl sleep
if [[ "$ILT_DEPLOY_TEST_MODE" != "1" ]]; then ilt_require_commands flock systemctl; fi
ilt_acquire_lock

current="$(ilt_current_release)"
[[ -L "$ILT_ROOT/previous" ]] || ilt_die "нет сохранённой previous версии"
previous="$(readlink -f -- "$ILT_ROOT/previous")"
[[ "$previous" == "$ILT_RELEASES/"* && -d "$previous" ]] || ilt_die "previous release находится за пределами releases/"
ilt_validate_release "$previous" "$(basename -- "$previous")" >/dev/null
[[ "$previous" != "$current" ]] || ilt_die "previous уже является активной версией"

ilt_atomic_link "$current" "$ILT_ROOT/previous"
ilt_atomic_link "$previous" "$ILT_ROOT/current"
if ilt_systemctl restart "$ILT_SERVICE_NAME" && ilt_wait_health; then
    ilt_info "Откат выполнен: активна версия $(basename -- "$previous")."
    exit 0
fi

ilt_info "Откат не прошёл health check; возвращается прежняя active версия."
ilt_atomic_link "$previous" "$ILT_ROOT/current"
ilt_atomic_link "$current" "$ILT_ROOT/previous"
ilt_systemctl restart "$ILT_SERVICE_NAME" || true
ilt_die "rollback release не прошёл health check"
