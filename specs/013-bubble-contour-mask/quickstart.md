# Quickstart: Bubble Contour Mask

## Dev check

```powershell
venv\Scripts\activate
python -m pytest tests/unit/test_bubble_contour.py tests/unit/test_page_steps.py -q
```

## Manual

1. Open a page with oval dialogue balloons and loose detector boxes.
2. Run translate/cleanup.
3. Confirm: no rectangular corner cleanup outside the bubble; no thick uncleared ring inside along the outline.

## Fixture idea

White page, black-outline white ellipse, dark text glyphs inside, `bubble_bbox` = loose square around ellipse. Assert mask misses square corners and covers near-outline interior band.
