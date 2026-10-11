# Data Model: Flutter Shell Host

No server document changes. New artifacts live under the existing data root.

| Entity | Location | Shape | Notes |
|--------|----------|-------|-------|
| Handshake | `<data>/api.json` | `{port: int, token: str}` | Written by sidecar; deleted on clean exit; host removes stale before spawn |
| Session token | `<data>/session.token` | plain text | Existing artifact, reused by sidecar |
| Instance record | `<data>/instance.json` | `{pid: int, port: int}` | **Host-owned** (Flutter IPC endpoint); sidecar never writes it |
| Sidecar status | host memory | `starting / ready / stopping / dead / authError / attach` | `SidecarController` → `ShellState` |
| Bootstrap view | host memory | raw `GET /api/bootstrap` map | Typed models arrive in 022+ |
| SSE frame | host memory | `{event: String, data: Map}` | Parsed by `SseReader` |
| Shell settings | from bootstrap `settings` | `theme`, `ui_scale` | Drive chrome theme/scale |

State machine (host):

```text
idle → starting → (attach? →) ready → stopping → idle
              ↘ error(timeout/exit/401) → retry → starting
ready → reconnecting(sse) → ready
```
