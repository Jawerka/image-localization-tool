# Tasks: 020-editor-shell-polish

- [x] T001 Merge v2 surface tokens into `web/css/tokens.css` with `--ui-scale` calcs; align `--pages-w` / `--inspector-w` / `--toolbar-h`
- [x] T002 Add `web/css/shell-v2.css` (dock, scene, panel collapse, appbar polish); link from `index.html`
- [x] T003 Restructure `web/index.html`: floating dock from `viewer__bar`, panel toggles; keep all smoke `data-role`s
- [x] T004 Extend `web/icons/icons.svg` with v2 symbols (panel-left/right, grip, fit-width, more-h as needed)
- [x] T005 Add `web/js/shell_chrome.js` — panel collapse + brush-size popover; wire from `main.js`
- [x] T006 Update `editor.css` / `main.css` / `app.css` so dock replaces top viewer bar layout
- [x] T007 Add `scripts/export_tokens.py` + generate `web/tokens.json`
- [x] T008 JS unit for shell chrome helpers if extracted; update any broken JS tests
- [x] T009 Run `npm run test:js` and `pytest tests/e2e/test_ui_smoke.py -m ui`
- [x] T010 Keep `web/mockups/next/` as reference; ensure old hub link remains
