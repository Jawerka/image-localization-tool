# Quickstart validation
1. Run targeted pytest/node/Playwright regressions for each changed subsystem.
2. Run Python unit/integration, JS and browser suites; correct obsolete picture expectation using visible pixels.
3. Run all unique test-img originals through v2 with allowed VLM, serially, to a fresh output folder; inspect original/clean/result and warnings automatically, without manual region edits.
4. Compare mask regressions using identical automatic regions, keeping ground truth out of runtime input.
5. Prepare extension artifact; dry run on temporary installation, apply and rollback with protected files; then repeat actual target dry run before authorized extension update.
6. Record versions, pass/fail and external limitations in a separate report. Do not broaden validation 007.
