# Feature Specification: Deploy Extension + Inno Check

**Branch**: `009-deploy-extension-inno`  
**Created**: 2026-10-09  
**Input**: Inventory 16/18 — script to deploy unpacked Chromium extension beside apps; clear Inno Setup presence check so installer builds are intentional, not surprise skips.

## User Stories

### US1 — Deploy extension (P1)
Maintainer runs one script that builds unpacked Chromium extension and mirrors it to the local apps extension folder used for Chromium load-unpacked.

### US2 — Know if Inno is available (P1)
Maintainer can run a check script that reports whether ISCC.exe is found and how to install Inno Setup 6; optional winget install when requested. build-windows remains able to SkipInno.

## Requirements
- FR-001: deploy-extension script builds via existing builder and mirrors Chromium unpack to configurable dest.
- FR-002: check-inno script reports ISCC path or missing + install hint; optional -Install via winget when available.
- FR-003: Unit static checks for new scripts (ASCII / key switches).
- FR-004: Flutter out of scope.

## Success Criteria
- SC-001: One command updates apps extension tree.
- SC-002: One command answers “can I build the installer?”
- SC-003: Inventory 16 (extension half) and 18 guidance addressed.
