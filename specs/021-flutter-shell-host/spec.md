# Feature Specification: Flutter Shell Host & Python API Sidecar

**Feature Branch**: `021-flutter-shell-host`

**Created**: 2026-10-10

**Status**: Draft

**Input**: Flutter Windows host + Python `--api` sidecar. Python: `python -m src.app --api` runs local HTTP without window, writes `api.json` `{port, token}`, never writes `instance.json`, optional one-line stdout handshake, `--parent-pid` orphan watchdog. Flutter: spawn sidecar, poll handshake, `Cookie: ilt_session` REST, self-written SSE reader on `package:http`, ChangeNotifier state, shell v2 chrome skeleton, single-instance via own IPC → `/api/drop`, dev attach `--dart-define=ILT_ATTACH=1`. Flutter pin ≥ 3.47.7. `python -m src.app` (pywebview) stays untouched.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Host owns sidecar lifecycle (Priority: P1)

When the Flutter host starts, it spawns `python -m src.app --api --parent-pid=<host_pid>`, waits for the handshake (`api.json` or the stdout line), and renders the shell. When the host exits (any path: close, crash, kill), the Python sidecar dies too and leaves no orphan process and no stale `api.json`.

**Why this priority**: Without lifecycle control there is no cutover path; orphan sidecars would hold ports and data locks.

**Independent Test**: Start the host, close it; `Get-Process python` shows no sidecar; `api.json` is removed. Kill the sidecar externally; the host shows a reconnect/error state and can respawn.

**Acceptance Scenarios**:

1. **Given** no sidecar is running, **When** the host starts, **Then** a sidecar is spawned with `--api --parent-pid` and the shell renders after handshake (target ≤ 8 s cold start).
2. **Given** the host is running, **When** the host process exits, **Then** the sidecar exits within ~2 s (parent watchdog) and `api.json` is deleted.
3. **Given** the sidecar is killed externally, **When** the host notices the process is gone, **Then** the UI shows the failure state with a Retry action instead of freezing.

---

### User Story 2 - Cookie-auth REST and live events (Priority: P1)

The host talks to the sidecar over `127.0.0.1` only. Every REST call and the SSE stream carry `Cookie: ilt_session=<token>` from the handshake; requests without it stay 401. Job/page events arrive over `GET /api/events` and update host state; the stream reconnects automatically after drops.

**Why this priority**: The whole UI depends on the API contract and event freshness; auth must not be bypassed or duplicated.

**Independent Test**: Flutter unit tests assert the cookie header on requests and parse SSE frames (`event:`/`data:`, keep-alive comments ignored) from a mock streamed response.

**Acceptance Scenarios**:

1. **Given** a valid handshake, **When** the host calls `/api/bootstrap`, **Then** the request carries the session cookie and the payload drives host state.
2. **Given** the token is wrong or missing, **When** a request is made, **Then** the API answer is 401 and the host surfaces an auth error (no silent retry loop).
3. **Given** the SSE connection drops, **When** the reader reconnects, **Then** missed pending events are replayed by the server and the UI does not duplicate-render them.

---

### User Story 3 - Dev attach and single instance (Priority: P2)

A developer can attach the host to an already running sidecar (`--dart-define=ILT_ATTACH=1`, no spawn, no kill). A second host launch focuses the first window and forwards its file paths through the host's own IPC to the sidecar via `/api/drop`.

**Why this priority**: Attach keeps daily development with `python -m src.app --api`; single instance preserves the existing user contract (paths open in the running app).

**Independent Test**: Launch sidecar manually, run host in attach mode; it renders without spawning. Launch the host twice; the second exits quickly and the first receives the dropped path.

**Acceptance Scenarios**:

1. **Given** `ILT_ATTACH=1` and a running sidecar, **When** the host starts, **Then** it connects and never kills the sidecar on exit.
2. **Given** a running host, **When** a second instance starts with a path argument, **Then** the first instance receives the path, its window is focused, and the second exits 0.

---

### User Story 4 - Shell chrome skeleton (Priority: P3)

The host renders shell v2 chrome (slim app bar, pages rail, scene, inspector rail, bottom dock placeholders) themed from `web/tokens.json` parity, with app bar actions for sidecar status/restart. Screens are filled by 022–025; this feature proves the shell can host them.

**Why this priority**: Establishes the visual frame early; full screens are separate features.

**Independent Test**: Widget test pumps the shell with a fake ready state; regions render with `data-role`-equivalent keys.

**Acceptance Scenarios**:

1. **Given** the host is ready, **When** the shell renders, **Then** app bar, rails and dock placeholders exist and status reflects the sidecar.
2. **Given** settings theme dark/light and UI scale 100–150, **When** the shell renders, **Then** it follows them from bootstrap settings.

---

### Edge Cases

- Stale `api.json` from a crashed previous run: host removes it before spawn; handshake must not reuse a port/token of a dead process.
- Sidecar exits during startup (e.g. missing WebView2 is irrelevant here, but missing config/model dirs): host times out (~20 s) and shows the captured stderr/log line.
- Port collision on sidecar start: sidecar uses an ephemeral 127.0.0.1 port; failure is surfaced through a non-zero exit.
- `python -m src.app --api` with `--remote`: LAN listener opt-in only; default API sidecar must not open LAN.
- Non-Windows dev hosts: attach mode only; spawn uses `sys.executable`-equivalent `python` from config.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `python -m src.app --api` MUST run the local HTTP API without importing/opening webview and without writing or honoring `instance.json`.
- **FR-002**: `--api` MUST write `api.json` `{port, token}` (0600 best-effort) plus `session.token`, print a one-line JSON handshake to stdout when stdout is writable, and delete `api.json` on clean exit.
- **FR-003**: `--api --parent-pid <pid>` MUST exit when the parent process disappears (poll ≤ 1 s), closing HTTP and queue resources.
- **FR-004**: The host MUST spawn the sidecar with `--api --parent-pid` and MUST kill it on exit (normal, error, and crash paths via platform facilities).
- **FR-005**: The host MUST resolve the handshake from stdout first (dev/console) and by polling `api.json` as fallback (frozen), with a startup timeout that produces a visible error state and Retry.
- **FR-006**: All host REST calls and the SSE subscription MUST send `Cookie: ilt_session=<handshake token>`; a 401 MUST surface as an auth error state, not retry forever.
- **FR-007**: The SSE reader MUST be self-written on `package:http` `StreamedResponse` (no third-party SSE package), parse `event:`/`data:` frames, ignore comment keep-alives, and reconnect with bounded backoff on drop/IO errors.
- **FR-008**: Host state MUST be `ChangeNotifier`/`InheritedNotifier` based; no state-management package beyond Flutter SDK.
- **FR-009**: The host MUST own single-instance: it writes its own `instance.json` `{pid, port}` for its own IPC endpoint; a second launch forwards paths via that IPC; the first host forwards them to the sidecar with `POST /api/drop` and focuses its window.
- **FR-010**: `--dart-define=ILT_ATTACH=1` MUST skip spawn/kill and attach to a running sidecar (handshake source: explicit `ILT_API_JSON`/env override, else default data-root `api.json`).
- **FR-011**: The shell chrome skeleton MUST render app bar, pages rail, scene, inspector rail and dock placeholders, theme/scale from bootstrap settings, using tokens exported to `web/tokens.json`.
- **FR-012**: `python -m src.app` (pywebview), `--headless`, CLI, extension and LAN paths MUST remain behavior-compatible; `--api` must not alter them.
- **FR-013**: Flutter code MUST be analyzable and tested on Windows CI (`flutter analyze`, `flutter test`); sidecar spawn smoke tests remain local (documented), not CI-blocking.
- **FR-014**: Dependency set MUST stay `http`, `file_selector` (plus dev `flutter_test`, `flutter_lints`); no `cookie_jar`, no SSE package, no state-management package.
- **FR-015**: Target Flutter SDK MUST be pinned in docs as ≥ 3.47.7 stable; local bootstrap may run on 3.44.0 (`environment.sdk: ^3.12.0`), upgrade before 026 cutover.

### Key Entities

- **Handshake (`api.json`)**: `{port: int, token: str}` written by the sidecar; source of host connection info.
- **SidecarController**: host-side lifecycle (spawn, handshake poll, health, kill, attach) exposing status to state.
- **IltApi**: cookie-authenticated REST client (`GET/POST/PUT` JSON) plus `events()` SSE stream factory.
- **SseFrame**: parsed `{event, data}` pair from the reader.
- **ShellState**: `ChangeNotifier` holding sidecar status, bootstrap payload, event cursor and error text.
- **InstanceRecord**: `{pid, port}` for the host-owned single-instance IPC; distinct from the sidecar's non-existent record.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Close host → no `python` sidecar process remains within 2 s (verified in 026 smoke; local check in 021).
- **SC-002**: Cold start (spawn → shell rendered with bootstrap) ≤ 8 s on the reference Windows machine.
- **SC-003**: Requests without cookie receive 401 from the live sidecar (proven in pytest for the server and in Flutter unit tests for the client).
- **SC-004**: `flutter analyze` reports no errors and `flutter test` is green on `windows-latest` CI; existing Python/JS suites stay green.
- **SC-005**: Second launch forwards a path and exits 0 in ≤ 1 s while the first instance shows the page.
- **SC-006**: `python -m src.app --headless --remote` and the pywebview window path behave exactly as before (existing pytest suites unchanged).

## Assumptions

- Windows 10/11 + WebView2 from the existing app remain the deployment target; Flutter Windows needs VS 2022 Desktop C++ only at build time.
- The sidecar communicates only over loopback; firewall rules are not required.
- 022–025 provide actual screens; 021 delivers chrome placeholders and wiring only.
- CI runs `flutter analyze`/`flutter test` with the SDK action (stable ≥ 3.47.7 when available; local 3.44.0 during bootstrap).
