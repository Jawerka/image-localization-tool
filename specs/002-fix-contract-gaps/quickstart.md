# Quickstart: Fix Contract Gaps

## Verify classification

```powershell
venv\Scripts\activate
pytest tests/unit/test_rapid_ocr_guess_type.py tests/unit/test_vlm_ocr.py -q
```

Expect: balloon CAPS → dialogue; short free label → sign; free shout → sfx; VLM prompt forbids balloon-as-sfx.

## Verify cleaning

```powershell
pytest tests/unit/test_lama_inpainter.py -q
```

Expect: existing flat-fill tests still pass; neighbor-ink case keeps neighbor glyphs and does not call LaMa.

## Manual PROBLEMS check

Open `docs/PROBLEMS.md`: no sections on large extension button / instant hover / every img>180px; no open «Текст в облачке распознаётся как звук» after the fix; Flutter and other wishlist intact.
