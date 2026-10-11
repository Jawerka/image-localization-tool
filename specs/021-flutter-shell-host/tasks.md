# Tasks: 021-flutter-shell-host

## Python sidecar

- [x] T001 Verify/complete `--api` + `--parent-pid` in `src/app/desktop.py` (api.json, stdout handshake, no instance.json, clean exit deletes api.json)
- [x] T002 Unit tests: `parse_args` api flags; `_write_api_ready` payload/mode; `_parent_alive` true/false; `launch` dispatch to `run_api`
- [x] T003 Integration test: `run_api` in thread with dead-parent helper process → api.json appears, cookie request works, parent killed → exit and file removed
- [x] T004 Run `pytest tests/unit/test_app_desktop.py tests/unit/test_app_server.py -q` (42 passed)

## Flutter host skeleton

- [x] T005 `apps/desktop/pubspec.yaml`: add `http`, `file_selector`; keep `flutter_lints`
- [x] T006 `lib/src/sidecar/handshake.dart`: ApiReady model + parse + data-root candidate resolution (env overrides, portable, LOCALAPPDATA)
- [x] T007 `lib/src/sidecar/sidecar_controller.dart`: spawn/kill/attach, stdout line reader, api.json poll, startup timeout, status callbacks
- [x] T008 `lib/src/api/sse.dart`: frame parser + reconnect reader
- [x] T009 `lib/src/api/ilt_api.dart`: cookie JSON client (GET/POST), `events()` stream
- [x] T010 `lib/src/state/shell_state.dart`: ChangeNotifier (status, bootstrap, last error, retry)
- [x] T011 `lib/src/ui/shell.dart`: app bar + pages rail + scene + inspector + dock placeholders, status/retry UI
- [x] T012 `lib/src/app.dart` + `lib/main.dart`: wiring, attach mode, single-instance IPC → `/api/drop`
- [x] T013 Single-instance: write/read host-owned `instance.json`, second-launch forward + exit; focus окна отложен в 026 (нет win32/ffi в deps — FR-009 обновлён)

## Tests & CI

- [x] T014 `test/handshake_test.dart`, `test/sse_test.dart`, `test/api_client_test.dart` (MockClient cookie/401), `test/sidecar_controller_test.dart` (fake spawner/reader), `test/single_instance_test.dart`, `test/shell_state_test.dart`
- [x] T015 Replace `test/widget_test.dart` counter test with shell smoke (fake ready state)
- [x] T016 `flutter analyze` clean + `flutter test` 33 passed (local 3.44.0; target pin ≥ 3.47.7 recorded in README)
- [x] T017 CI: add `flutter` job (`windows-latest`, analyze + test)
- [x] T018 Update `apps/desktop/README.md`: pin, dev/attach/run instructions

## Converge

- [x] T019 Manual converge: verify FR-001…FR-015 evidence (pytest, flutter, manual host run), append results here
  - pytest: `test_app_desktop.py` + `test_app_server.py` + `test_app_settings.py` 52 passed; full `tests/unit` 380 passed, 1 pre-existing unrelated failure (`test_text_style.py::test_rotated_layer_stays_on_block_center`, fails на чистом HEAD)
  - `npm run test:js`: 45 passed (Node 24.14.1 ≥ 21)
  - `flutter analyze` clean; `flutter test` 33 passed; `flutter build windows --debug` OK
  - Live smoke (debug exe + isolated `ILT_DATA_DIR`): cold start ≤ 1.3–5.7 s; cookie bootstrap 200 / no cookie 401; second launch exited 0 и страница появилась в первом (project «Проект», 1 page); graceful close → sidecar за 0.22 s, `api.json` и `instance.json` удалены; убийство хоста → sidecar гаснет после сохранения очереди (detect 0.4 s; задержка = запись queue.json 166 МБ в реальном каталоге — pre-existing поведение `AppState.close`)
  - FR-009 focus окна отложен в 026 (нет win32/ffi в deps); остальные FR подтверждены
- [x] T020 Хвост US1#3: `ShellState._watchExit` слушает `processExitCode` → error + Retry (run-guard против ложных срабатываний при retry/dispose); `flutter analyze` clean, `flutter test` 35 passed

