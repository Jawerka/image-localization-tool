# Implementation Plan: Editor Shell v2 Port

**Branch**: `020-editor-shell-polish` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/020-editor-shell-polish/spec.md`

## Summary

Port approved shell v2 from `web/mockups/next` into live `web/`: merge design tokens into `tokens.css` (via `--ui-scale`), restyle chrome (slim app bar, floating dock, collapsible rails, scene), wire JS for dock/panels/popovers, extend `icons.svg`, generate `tokens.json`. Preserve `data-role` for e2e. No Flutter / API / pywebview changes.

## Technical Context

**Language/Version**: HTML/CSS/JS (ES modules), Python 3.10+ for token generator only  
**Primary Dependencies**: existing web UI, pytest Playwright e2e, Node ≥21 for JS tests  
**Storage**: N/A (theme/scale already in settings.json)  
**Testing**: `npm run test:js`, `pytest tests/e2e/test_ui_smoke.py -m ui`  
**Target Platform**: Desktop app WebView2 / `--browser`  
**Project Type**: desktop-app UI  
**Constraints**: Minimal diff; keep API; `--ui-scale` not CSS zoom; no sprite.js in live web  
**Scale/Scope**: Main shell screens + token export

## Constitution Check

- Pipeline v2 untouched — PASS  
- Minimal diff (UI-only) — PASS  
- Russian comments in new scripts — PASS  
- No Flutter / entry removal — PASS (FR-008)

## Project Structure

```text
specs/020-editor-shell-polish/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/data-role.md
└── tasks.md

web/
├── index.html
├── css/tokens.css, shell-v2.css, editor.css, main.css, …
├── js/shell_chrome.js (new), viewer.js, main.js, …
├── icons/icons.svg
└── mockups/next/          # design reference (keep)

scripts/export_tokens.py
web/tokens.json            # generated
```

## Complexity Tracking

N/A — no constitution violations.
