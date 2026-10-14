# Проверка

1. venv/Scripts/python.exe -m pytest tests/unit/test_downloads.py tests/unit/test_preparation.py tests/unit/test_runtime.py -q
2. Полный pytest; в apps/desktop flutter analyze и flutter test.
3. scripts/release.ps1 -Prepare -DryRun: фиксированный каталог, никаких разрешений зависимостей.
4. Чистая frozen portable без manifest env: CPU/offline en→ru, остановить/возобновить, обработать страницу v2, повторить без сети.
5. NVIDIA: CUDA-операция + страница. Linux frozen: CPU/Argos + страница.
6. Только после ручной приёмки scripts/release.ps1 -Publish, проверяя сохранённые хэши.
[API](contracts/preparation-api.md), [модель данных](data-model.md).
