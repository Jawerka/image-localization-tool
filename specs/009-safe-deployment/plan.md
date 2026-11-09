# Implementation Plan: Безопасный деплой

**Branch**: codex/009-safe-deployment | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

## Summary

Windows обновляет только desktop/sidecar/web/fonts; модели при явном IncludeModels дополняются без очистки. Каждый запуск сначала вызывает robocopy /L. Пользовательские root-каталоги не входят в копирование. До записи создаётся свежая копия кода и data рядом с установкой.

LAN: PowerShell-вход сохраняет прежние параметры, Python stdlib формирует манифест src/web. Через SSH выполняется read-only план по реальному серверу. При применении — повторная сверка, эксклюзивная блокировка, проверка архива, stage, остановка службы, копия data/config и изменяемого кода, атомарная замена отдельных файлов. При ошибке кода/health — восстановление кода и рестарт. Модели/venv не меняются, устаревшие файлы не удаляются.

## Technical Context

PowerShell 5.1+, Windows robocopy; Python 3.10+ и stdlib; Linux SSH/scp/systemd. Новых зависимостей нет. SSH использует известные ключи (StrictHostKeyChecking=yes). Backup на сервере приватный, рядом с установкой. Манифест не содержит пользовательских данных или секретов.

## Constitution Check

Пайплайн v2 не меняется, настройки приложения не меняются; пользовательские каталоги сохраняются. Новые Python-комментарии и docstring на русском, PS-скрипты остаются ASCII для существующего контракта. Работа в отдельной ветке, без push/PR/слияния. Проверки проходят на fixture и целевом LAN; произвольные серверы не заявляются проверенными.

## Project Structure

scripts/deploy-windows.ps1, deploy-lan.ps1, lan_deploy.py, lan_deploy_remote.py; tests/unit/test_deploy_scripts.py и test_lan_deploy.py; docs/DEPLOYMENT_SAFETY.md. Постоянное правило в AGENTS.md и .cursor/rules/deployment-dry-run.mdc.

## Complexity Tracking

Небольшой stdlib-помощник нужен для проверки TAR, хешей и отката без опасной интерполяции shell-команд. Нового сервиса и API нет.
