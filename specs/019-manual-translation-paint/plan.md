# Plan: Manual Translation Autosave + Paint

- `web/js/inspector.js` — `deferApply: false` for text/translation
- `src/app/worker.py` — `_drawable`: translation strip + not skip
- tests: JS source check; unit for `_drawable`
