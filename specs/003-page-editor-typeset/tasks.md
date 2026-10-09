# Tasks: Page Editor and Typeset

**Input**: `/specs/003-page-editor-typeset/`

## Phase 1: Setup

- [x] T001 Confirm `specs/003-page-editor-typeset/spec.md` and feature.json
- [x] T002 [P] Write plan/research/data-model

## Phase 2: Foundational

- [x] T003 Confirm `_put_document` still applies on stroke diff once saved (`src/app/server.py`)

## Phase 3: US1 Keep result visible (P1)

- [x] T004 [US1] Keep prior result image while status is not ready in `web/js/viewer.js` `setSrc` / `showResultGap`

## Phase 4: US2 Done instead of auto-run (P1)

- [x] T005 [US2] Add `deferApply` to `editDocument` in `web/js/state.js` + `commitDeferredEdits`
- [x] T006 [US2] Stroke end uses `deferApply` in `web/js/viewer.js`
- [x] T007 [US2] Add «Готово» control in `web/index.html` + wire in `web/js/main.js`

## Phase 5: US3 Brush preview (P2)

- [x] T008 [US3] Blue translucent stroke preview in `web/js/viewer.js`

## Phase 6: US4–US6 Typeset (P2)

- [x] T009 [US4] Ensure ordinary first layout does not copy ink rotation/warp (verify `page_pipeline` / segmenter; fix if needed)
- [x] T010 [US5] Align rotation pivot with text-field (bbox) center in typesetter/viewer
- [x] T011 [US6] Balloon inset ~2–3 px in `layout_inset_px`
- [x] T012 [US6] Cap short-reply font using neighbor balloon sizes in typesetter

## Phase 7: US7–US9 (P3)

- [x] T013 [US7] Fix arc/wave labels vs geometry in `text_warp.py` / UI labels
- [x] T014 [US7] Mesh creates points and bends in correct coordinate space
- [x] T015 [US8] Move frequent style controls onto block card in inspector/web
- [x] T016 [US9] Upscale small pages (long side ~2000) before layout

## Phase 8: Verify

- [x] T017 Verify reset-styles on block card (FR-014)
- [x] T018 Verify SFX first layout without ink angle (FR-015)

## Phase 9: Polish

- [x] T019 Unit tests for inset (typesetter); deferApply — ручная проверка / позже JS
- [x] T020 Record remaining work in `progress.md`
