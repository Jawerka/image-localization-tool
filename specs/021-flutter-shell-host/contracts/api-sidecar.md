# Sidecar API contract (locked by this feature)

Loopback-only HTTP; `Host` must be `127.0.0.1:<port>` or `localhost:<port>`.

## `--api` startup

| Artifact | Value |
|----------|-------|
| stdout | one line: `{"port": int, "token": str, "api_json": "<path>"}` (when stdout writable) |
| `<data>/api.json` | `{"port": int, "token": str}` (0600 best-effort) |
| `<data>/session.token` | `token` |
| `<data>/instance.json` | **not written** |

Корень `<data>`: портативный `data` рядом с установкой, иначе
`%LOCALAPPDATA%\ImageLocalizationTool`; переменная `ILT_DATA_DIR` задаёт
каталог явно и на стороне Python (`src/app/paths.py`), и на стороне хоста.

Exit conditions: `--parent-pid` gone (poll 0.5 s) / Ctrl+C / process kill. On clean exit `api.json` is deleted.

## Auth

| Header | Value |
|--------|-------|
| `Cookie` | `ilt_session=<token>` |
| Others | none (Origin may be absent; if present must be `http://127.0.0.1:<port>` / `http://localhost:<port>`) |

Missing/wrong cookie → `401 {"error": "Не авторизован"}` on `/api/*` except `POST /api/session`.

## Endpoints used by the host (021)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/bootstrap` | settings, project, pages, llm, busy, paths, package |
| POST | `/api/drop` | `{"paths": [...]}` — open files/folders (single-instance forward) |
| GET | `/api/events` | SSE: `event: <type>\ndata: <json>\n\n`, `: keep-alive\n\n` every 15 s, `Connection: close` |

## Single instance (host-owned, not Python)

| Artifact | Owner |
|----------|-------|
| `<data>/instance.json` `{pid, port}` | Flutter host (its own `ServerSocket`) |
| Line protocol | one UTF-8 JSON line `{"paths": ["..."]}` then close |

Second launch: read record → pid alive? → connect → send paths → exit 0. First host: receive → `POST /api/drop` with cookie → focus window.
