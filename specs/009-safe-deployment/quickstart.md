# Проверка

1. `venv/Scripts/python.exe -m pytest tests/unit/test_lan_deploy.py tests/unit/test_deploy_scripts.py -q`
2. `scripts/deploy-windows.ps1 -DryRun` — только реальные managed-каталоги, без записи.
3. `scripts/deploy-lan.ps1 -DryRun -Report output/safe-deployment/lan-dry-run.json`
4. Проверить план, затем `scripts/deploy-lan.ps1 -Report output/safe-deployment/lan-applied.json`.
5. Проверить health, хеши манифеста и данные относительно свежего backup. Смена артефактов/цели требует повторного dry run.
