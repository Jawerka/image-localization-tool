# Preparation API

Существующие server auth/CSRF распространяются на новые маршруты.
- POST /api/preparation/plan: translator_backend/source_lang/target_lang/device → items,total,missing,torch,required_space.
- GET /api/preparation: persisted snapshot.
- POST /api/preparation/start: selection либо сохранённый план; busy не запускает вторую задачу.
- POST /api/preparation/pause и /resume: безопасная остановка/продолжение.
- POST /api/preparation/cache/clear: не затрагивает активные задачи.
- SSE preparation.progress: полный snapshot с общим прогрессом.
Ошибки network/disk/permission/integrity/compatibility/busy/unsupported. Legacy runtime/models endpoints и CLI deploy сохраняются.
release.ps1 -Prepare готовит candidate; -Publish проверяет тот же комплект и публикует после ручной проверки; -DryRun не меняет GitHub.
