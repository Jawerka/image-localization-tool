# Quickstart: 005 Editor Harden

```powershell
venv\Scripts\activate
pytest tests/e2e/test_ui_smoke.py -m ui -q
# or focused:
pytest tests/e2e/test_ui_smoke.py -k "mask_done or details" -m ui -q
```

Manual: open page → translate → select region → close «Искажение» → edit translation → section stays closed. Brush + mask → stroke → local overlay → «Готово».
