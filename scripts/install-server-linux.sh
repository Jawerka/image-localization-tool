#!/usr/bin/env bash
# Идемпотентно установить packaged Linux-сервер и зарегистрировать systemd unit.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/linux-deploy-common.sh
source "$SCRIPT_DIR/linux-deploy-common.sh"

BUNDLE="$SCRIPT_DIR"
SKIP_COMPONENTS=0

usage() {
    cat <<'EOF'
Использование: sudo install-server-linux.sh [--bundle PATH] [--root PATH]
                                           [--skip-components] [--health-timeout SECONDS]

Первичная установка Linux-сервера. Повторный запуск той же версии безопасен.
Для смены версии используйте update-server-linux.sh.
EOF
}

while (($#)); do
    case "$1" in
        --bundle) (($# >= 2)) || ilt_die "для --bundle нужен путь"; BUNDLE="$2"; shift 2 ;;
        --root) (($# >= 2)) || ilt_die "для --root нужен путь"; ILT_ROOT="$2"; ILT_RELEASES="$ILT_ROOT/releases"; ILT_SHARED="$ILT_ROOT/shared"; ILT_LOCK_FILE="$ILT_ROOT/.deployment.lock"; shift 2 ;;
        --skip-components) SKIP_COMPONENTS=1; shift ;;
        --health-timeout) (($# >= 2)) || ilt_die "для --health-timeout нужны секунды"; ILT_HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) ilt_die "неизвестный аргумент: $1" ;;
    esac
done

ilt_require_root
ilt_validate_root
ilt_require_commands id python3 mkdir cp mktemp mv rm ln readlink sed cmp chmod install curl sleep
if [[ "$ILT_DEPLOY_TEST_MODE" != "1" ]]; then ilt_require_commands flock systemctl; fi
[[ -d "$BUNDLE" ]] || ilt_die "не найден каталог релиза: $BUNDLE"
[[ -f "$BUNDLE/ilt.service" ]] || ilt_die "в релизе нет ilt.service"
version="$(ilt_validate_release "$BUNDLE")"

ilt_acquire_lock
ilt_prepare_layout

if [[ -L "$ILT_ROOT/current" ]]; then
    current="$(ilt_current_release)"
    current_version="$(basename -- "$current")"
    [[ "$current_version" == "$version" ]] || ilt_die "установлена версия $current_version; для $version используйте update-server-linux.sh"
    unit_changed="$(ilt_install_unit "$BUNDLE/ilt.service")"
    if [[ "$unit_changed" == "1" ]]; then
        ilt_systemctl daemon-reload
        ilt_systemctl enable "$ILT_SERVICE_NAME"
        ilt_start_and_check restart || ilt_die "сервис не прошёл проверку здоровья после обновления unit"
    else
        ilt_systemctl daemon-reload
        ilt_systemctl enable "$ILT_SERVICE_NAME"
        if ! ilt_health_ready; then
            ilt_start_and_check restart || ilt_die "сервис не прошёл проверку здоровья"
        fi
    fi
    ilt_info "Сервер версии $version уже установлен и отвечает на health API."
    exit 0
fi
[[ ! -e "$ILT_ROOT/current" ]] || ilt_die "путь current существует, но не является symlink"

release="$ILT_RELEASES/$version"
ilt_bundle_to_release "$BUNDLE" "$release"
if [[ "$SKIP_COMPONENTS" == "0" ]]; then
    ilt_info "Подготовка компонентов для первого запуска..."
    ilt_prepare_components "$release" || ilt_die "подготовка компонентов завершилась ошибкой; повторите установку после исправления сети/места"
fi

ilt_install_unit "$BUNDLE/ilt.service" >/dev/null
ilt_atomic_link "$release" "$ILT_ROOT/current"
ilt_systemctl daemon-reload
ilt_systemctl enable "$ILT_SERVICE_NAME"
if ! ilt_start_and_check start; then
    ilt_systemctl stop "$ILT_SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f -- "$ILT_ROOT/current"
    ilt_systemctl disable "$ILT_SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f -- "$ILT_UNIT_DIR/$ILT_SERVICE_NAME"
    ilt_systemctl daemon-reload >/dev/null 2>&1 || true
    ilt_die "первый запуск не прошёл health check; active release не оставлен"
fi

ilt_info "Установлен Linux LAN-сервер $version. Health API готов: $ILT_HEALTH_URL"
