# Implementation Plan: Cutover — Flutter Host as the Shipped App

**Branch**: `026-cutover` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/026-cutover/spec.md`

## Summary

Ship the Flutter host (021–025) as the Windows app. Assemble `dist/ImageLocalizationTool` as `desktop/` (Flutter release) + `sidecar/` (PyInstaller onedir) + `web/` + `fonts/` (+ optional `models/`). Teach the host to resolve the frozen sidecar and the install root without env, keep portable `data`/models semantics identical for host and sidecar, focus the running window on a second launch (`win32`), strip the WebView2 prerequisite from the installer and clean the old layout on upgrade, build the Flutter app with the Python-owned version, and upgrade the Flutter pin to stable ≥ 3.47.7.

## Technical Context

**Language/Version**: Dart/Flutter — upgrade to stable ≥ 3.47.7 (local 3.44.0 today); Python 3.10+ sidecar unchanged; PowerShell build scripts
**Primary Dependencies**: Flutter SDK; `package:http`, `file_selector`; **+ `win32` (ffi)** — justified exception to 021 FR-014 for window focus; no state-management packages
**Storage**: user data unchanged (`data/` beside install, else `%LOCALAPPDATA%`/`%APPDATA%`); installer cleans obsolete files only
**Testing**: `flutter analyze`/`flutter test` on the new SDK; pytest for build/smoke/installer/paths; manual acceptance on the built dist
**Target Platform**: Windows 10/11 x64; per-user Inno install; VS 2022 Desktop C++ for release builds
**Constraints**: API/pipeline/web surfaces untouched; pywebview source entry stays; CI stays analyze+test only
**Scale/Scope**: packaging, host path resolution + focus, installer, docs pins

## Constitution Check

- Pipeline v2 untouched — PASS (no server pipeline edits; only `install_root()` env override)
- Minimal diff — PASS (one new Dart file + small edits to host resolution, scripts, installer)
- Russian comments/docstrings — PASS
- Local data not committed — PASS
- Compatibility boundaries — PASS (`python -m src.app`, `--browser`, `--headless`, extension, LAN untouched; new env is additive)
- New dependency (`win32`) — deliberate, named in spec FR-007 and here: native window focus cannot be done in pure Dart without FFI; `ffi` is the minimal veneer over dllimport

## Distribution layout

```text
dist/ImageLocalizationTool/     # {app}; staged by build-windows.ps1
├── desktop/                    # Flutter release bundle
│   ├── ImageLocalizationTool.exe   (BINARY_NAME)
│   ├── flutter_windows.dll, *.dll
│   └── data/                   # Flutter runtime assets — NOT user data
├── sidecar/                    # PyInstaller onedir
│   ├── ImageLocalizationTool.exe
│   └── _internal/
├── web/  fonts/
├── models/                     # optional (first-run download otherwise)
└── data/                       # optional portable user data
```

- PyInstaller `COLLECT` name changes `ImageLocalizationTool` → `ilt_sidecar` (exe name stays `ImageLocalizationTool`), so the build can stage it under `sidecar/` without clobbering the final dir.
- `{app}\data` no longer collides with Flutter's asset folder: the host never treats `desktop/data` as user data.

## Path resolution

| Who | Resolution |
|-----|------------|
| Host, sidecar command | `ILT_SIDECAR_EXE` → `{installRoot}/sidecar/ImageLocalizationTool.exe` → dev `ILT_PYTHON`/`python -m src.app --api` |
| Host, install root | frozen layout: parent of its exe dir (`desktop/` → `{app}`); dev: unresolved |
| Host, data root | `ILT_DATA_DIR` → dev `repoRoot/data` → `{installRoot}/data` → `%LOCALAPPDATA%\ImageLocalizationTool` |
| Sidecar, install root | `ILT_INSTALL_ROOT` (set by host at spawn) → frozen `sys.executable` dir → repo root |
| Sidecar, data root | unchanged `default_paths()` on top of `install_root()` |

`src/utils/paths.py::install_root()` gains the `ILT_INSTALL_ROOT` override; that single funnel covers `models/`, `fonts/` and the served `web/`.

## Window focus (US3)

- New `apps/desktop/lib/src/sidecar/window_focus.dart` (`win32`): `allowForegroundTo(pid)` (second process) and `focusMainWindow({pid})` (first process: find visible top-level window of its pid, `ShowWindow(SW_RESTORE)` + `SetForegroundWindow`); no-ops on non-Windows.
- `main.dart` single-instance callback always focuses first, then forwards non-empty paths (empty list = focus-only second launch).

## Packaging & installer

- `build-windows.ps1`: resolve flutter (`PATH` → `%LOCALAPPDATA%\flutter\bin\flutter.bat`), read version, `flutter build windows --release --build-name=<ver> --build-number=1`, PyInstaller, assemble the layout, stage web/fonts, optional models, `smoke_dist.py`, Inno.
- `smoke_dist.py`: check `desktop/ImageLocalizationTool.exe`, `desktop/flutter_windows.dll`, `desktop/data/flutter_assets`, `sidecar/ImageLocalizationTool.exe` + `sidecar/_internal` (torch check moves under sidecar), `web/index.html`, `fonts/`, no `web/mockups`.
- `installer/*.iss`: `[Icons]`/`[Run]` → `{app}\desktop\ImageLocalizationTool.exe`; `[InstallDelete]` old root exe + `_internal`; drop the WebView2 `[Code]` block and its test.
- `deploy-windows.ps1`: integrity checks for host, sidecar, `web/` (robocopy `/MIR` already removes stale root files).
- `windows/CMakeLists.txt` `BINARY_NAME` → `ImageLocalizationTool`; `Runner.rc` product/file description → "Image Localization Tool".

## Docs

- `apps/desktop/README.md`: pin stable ≥ 3.47.7, release-build layout, sidecar resolution.
- `docs/APP.md` + `README.md`: shipped app is the Flutter host; `python -m src.app` stays the dev/legacy pywebview entry.
- CI comment: stable channel, no exact patch pin.

## Project Structure

```text
specs/026-cutover/{spec,plan,tasks}.md

apps/desktop/
├── lib/src/sidecar/sidecar_controller.dart   # frozen-layout command resolution
├── lib/src/sidecar/data_root.dart            # installRoot/data instead of exeDir/data
├── lib/src/sidecar/window_focus.dart         # NEW: win32 focus
├── lib/main.dart                             # focus on second launch
├── pubspec.yaml                              # + win32
├── windows/CMakeLists.txt, windows/runner/Runner.rc
└── test/{handshake,sidecar_controller,data_root}_test.dart

src/utils/paths.py                            # ILT_INSTALL_ROOT
ImageLocalizationTool.spec                    # COLLECT name ilt_sidecar
scripts/build-windows.ps1, smoke_dist.py, deploy-windows.ps1
installer/ImageLocalizationTool.iss
tests/unit/{test_packaging,test_app_paths}.py
docs/APP.md, README.md, .github/workflows/ci.yml (comment only)
```

## Complexity Tracking

| Item | Why |
|------|-----|
| `win32` dependency | window focus deferred from 021; FFI is the only no-package-rewrite path, spec FR-007 allows it |
| `ILT_INSTALL_ROOT` env | sidecar sits in `sidecar/`, so `sys.executable` no longer locates models/fonts/web/portable data; one explicit override keeps one resolution rule |
| Two-bundle staging | Flutter needs its own dir for `data/`; Python onedir needs `_internal/`; root stays the stable user-data surface |
