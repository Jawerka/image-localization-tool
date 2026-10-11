# Research: Flutter Shell Host & Python API Sidecar

## Decision: Sidecar handshake via `api.json` (stdout optional)

**Choice**: Sidecar writes `api.json` `{port, token}` under the data root and prints one JSON line to stdout when writable; host reads stdout first, polls the file as fallback.

**Rationale**: Frozen GUI builds (`console=False`) have `sys.stdout is None`; `src/app/__main__.py` redirects to `logs/app.log`, so stdout cannot be the only source. File polling also survives restarts. Plan row: "Handshake | `api.json` `{port,token}` (+ опц. stdout); Flutter поллит файл (`_guard_stdio` / frozen)".

**Rejected**: control pipe protocol, Windows named pipe (extra native surface), reading the log file (racy).

## Decision: Orphan protection via `--parent-pid`, not job objects

**Choice**: Host spawns `python -m src.app --api --parent-pid=<pid>`; sidecar polls parent liveness every 0.5 s and exits when gone; host also kills on its own exit paths.

**Rationale**: `--parent-pid` is testable in pytest, works for attach-mode restarts, and mirrors the existing `src/app/worker.py` `start_parent_watch` precedent. Windows job objects would be stronger but tie the host to native code; 026 smoke verifies no orphans.

**URLs**: [Process groups / job objects background](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

## Decision: Own IPC for single instance + `/api/drop`

**Choice**: Host runs a loopback `ServerSocket`, writes host-owned `instance.json` `{pid, port}`; second launch sends one JSON line `{"paths": [...]}` and exits; first host forwards to sidecar `POST /api/drop` (cookie) and focuses the window.

**Rationale**: The sidecar must not own `instance.json` (plan row "sidecar не пишет `instance.json`"); the host owns window focus anyway. Line protocol reuses `parse_paths_message`/`encode_paths_message` shape from `src/app/desktop.py` for parity.

**URLs**: [`windows_single_instance`](https://pub.dev/packages/windows_single_instance) — evaluated; does not forward paths (plan table), so only the concept is adopted.

## Decision: Cookie header manual on `package:http`

**Choice**: `http.Client` wrapper adds `Cookie: ilt_session=<token>` and `Host` resolves to `127.0.0.1:<port>`; no `cookie_jar`.

**Rationale**: Single fixed token, no redirects, no cookie domain logic; `_host_allowed` in `src/app/server.py` requires `127.0.0.1:<port>` or `localhost:<port>` exactly; `_origin_allowed` permits missing Origin.

## Decision: Self-written SSE reader

**Choice**: Read `StreamedResponse.stream` via `utf8.decoder` + `LineSplitter`; accumulate `event:`/`data:` lines until blank line; ignore `:` comments; reconnect with backoff 1→15 s.

**Rationale**: Server (`_stream_events`) emits `event: <type>\ndata: <json>\n\n` and `: keep-alive\n\n` every 15 s; `Connection: close` per response. Contract is trivial — a package is not justified (plan row "SSE | Самописный ридер на `package:http` StreamedResponse").

## Decision: Handshake file location resolution

**Choice**: Attach/fallback candidates in order: explicit env `ILT_API_JSON` (full path), then portable `<sidecar_dir>/data/api.json`, then `%LOCALAPPDATA%/ImageLocalizationTool/api.json`; `ILT_DATA_DIR` overrides the data root for dev.

**Rationale**: Mirrors `src/app/paths.py` `default_paths()` (portable `data/` next to install, else `%LOCALAPPDATA%` projects root). Dev without portable dir can still point at the right root.

## Industry patterns (URL-backed)

| Pattern | Source | Mapping |
|---------|--------|---------|
| Process spawn + kill on exit | [`Process.start`](https://api.flutter.dev/flutter/dart-io/Process/start.html), [`Process.kill`](https://api.flutter.dev/flutter/dart-io/Process-class.html) | SidecarController |
| Streamed HTTP parsing | [`http` package](https://pub.dev/packages/http) `StreamedResponse` | SSE reader |
| Windows build prerequisites | [Flutter Windows building](https://docs.flutter.dev/platform-integration/windows/building); [Windows setup](https://docs.flutter.dev/platform-integration/windows/setup) | VS 2022 C++ requirement |
| State without packages | [`ChangeNotifier`](https://api.flutter.dev/flutter/foundation/ChangeNotifier-class.html), [`InheritedNotifier`](https://api.flutter.dev/flutter/widgets/InheritedNotifier-class.html) | ShellState |
| Native file dialogs (022/025) | [`file_selector`](https://pub.dev/packages/file_selector) | dependency added now, used later |

## SDK pin

Local bootstrap: Flutter **3.44.0** (Dart 3.12.0). Target pin recorded for docs/CI: **Flutter ≥ 3.47.7 stable** (plan decision); upgrade before 026 cutover, keep `environment.sdk: ^3.12.0` compatible floor.
