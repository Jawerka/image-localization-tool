#!/usr/bin/env bash
# Развернуть новую версию рядом со старой и активировать только после health check.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/linux-deploy-common.sh
source "$SCRIPT_DIR/linux-deploy-common.sh"

BUNDLE=""

usage() {
    cat <<'EOF'
Использование: sudo update-server-linux.sh --bundle PATH [--root PATH]
                                            [--health-timeout SECONDS]

Устанавливает только файлы приложения. Подготовленные модели и runtime-паки не меняются.
EOF
}

while (($#)); do
    case "$1" in
        --bundle) (($# >= 2)) || ilt_die "для --bundle нужен путь"; BUNDLE="$2"; shift 2 ;;
        --root) (($# >= 2)) || ilt_die "для --root нужен путь"; ILT_ROOT="$2"; ILT_RELEASES="$ILT_ROOT/releases"; ILT_SHARED="$ILT_ROOT/shared"; ILT_LOCK_FILE="$ILT_ROOT/.deployment.lock"; shift 2 ;;
        --health-timeout) (($# >= 2)) || ilt_die "для --health-timeout нужны секунды"; ILT_HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) ilt_die "неизвестный аргумент: $1" ;;
    esac
done

ilt_require_root
ilt_validate_root
ilt_require_commands id python3 mkdir cp mktemp mv rm ln readlink sed cmp chmod install curl sleep
if [[ "$ILT_DEPLOY_TEST_MODE" != "1" ]]; then ilt_require_commands flock systemctl; fi
[[ -n "$BUNDLE" && -d "$BUNDLE" ]] || ilt_die "укажите существующий каталог кандидата через --bundle"
version="$(ilt_validate_release "$BUNDLE")"
[[ -f "$BUNDLE/ilt.service" ]] || ilt_die "в релизе нет ilt.service"

ilt_acquire_lock
current="$(ilt_current_release)"
current_version="$(basename -- "$current")"
if [[ "$version" == "$current_version" ]]; then
    ilt_info "Версия $version уже активна."
    exit 0
fi

release="$ILT_RELEASES/$version"
ilt_bundle_to_release "$BUNDLE" "$release"
ilt_validate_release "$release" "$version" >/dev/null

# Запомнить последнюю здоровую версию до переключения active symlink.
previous_existed=0
previous_before=""
if [[ -L "$ILT_ROOT/previous" ]]; then
    previous_existed=1
    previous_before="$(readlink -f -- "$ILT_ROOT/previous")"
elif [[ -e "$ILT_ROOT/previous" ]]; then
    ilt_die "путь previous существует, но не является symlink"
fi
ilt_atomic_link "$current" "$ILT_ROOT/previous"
ilt_atomic_link "$release" "$ILT_ROOT/current"
if ilt_systemctl restart "$ILT_SERVICE_NAME" && ilt_wait_health; then
    ilt_info "Активирована версия $version; предыдущая сохранена в $ILT_ROOT/previous."
    exit 0
fi

ilt_info "Кандидат $version не прошёл health check; выполняется откат."
ilt_atomic_link "$current" "$ILT_ROOT/current"
if [[ "$previous_existed" == "1" ]]; then
    ilt_atomic_link "$previous_before" "$ILT_ROOT/previous"
else
    rm -f -- "$ILT_ROOT/previous"
fi
if ilt_systemctl restart "$ILT_SERVICE_NAME" && ilt_wait_health; then
    ilt_die "обновление отклонено; восстановлена здоровая версия $current_version"
fi
ilt_die "кандидат отклонён, но предыдущий сервис тоже не прошёл health check; current указывает на $current"
