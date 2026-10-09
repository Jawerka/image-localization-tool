# Plan 010

Tighten in `lama_inpainter.py`:
- Smaller dilate for LaMa window mask (5→3).
- Stricter ring ink rejection (bg distance / inlier ratio).
- Named constants for tests/docs.

Keep flat-fill neighbor tests green; add denser soft-neighbor regression.
