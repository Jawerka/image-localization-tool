# Quickstart: 020-editor-shell-polish

```powershell
python scripts\export_tokens.py
npm run test:js
python -m pytest tests/e2e/test_ui_smoke.py -m ui -q
python -m src.app --browser
```

Visual: open app, check editor dock + panel toggles; settings theme/scale 100/125/150 light/dark.
