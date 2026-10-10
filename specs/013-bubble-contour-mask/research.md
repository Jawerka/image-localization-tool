# Research: Bubble Contour Mask

**Feature**: 013-bubble-contour-mask  
**Date**: 2026-10-10

## Dual failure modes

1. **Exterior AABB corners** — retouch/cleanup marks pixels in detector-box corners outside the curved outline.
2. **Inner outline ring** — large fixed inset leaves an uncleared band between cleaned interior and the stroke.

## Sources

| Source | Finding | Decision |
| --- | --- | --- |
| MangaSeg (CVPR 2025) | Prefer **inner** boundary masks for translation/cleanup | Target semantics: up to inner stroke, not past it |
| Rigaud 2015 | Balloon as light connected component / topology | Use CC of light interior + seed from text |
| Rigaud ICDAR 2013 | Active contours for open balloons | Out of scope (complexity); defer |
| BallonsTranslator canny_flood / extract_ballon_mask | Flood from text; stop on edges; clip dilation to balloon | Closest practical pattern |
| StackOverflow flood-to-dark-border | Seeds inside, stop on dark border | Align with barrier flood |
| Specs 010 / 011 | LaMa ring tighten + soft paste | Keep; fix geometry upstream |

## Decision

**Classical edge-aware balloon interior** in `src/components/bubble_contour.py`:

- Seeds near text; barrier from dark / high-gradient outline.
- Keep CC containing seed; small inset (Config), not fixed 12 px.
- Fallback: ink dilated in ROI — never inscribed ellipse of AABB.
- No new neural balloon segmenter in 013.

## Alternatives rejected

| Alternative | Why not now |
| --- | --- |
| YOLO/U-Net balloon instance seg | New weights + engine; candidate 014 if classical fails on thought bubbles |
| Active contour snakes | Heavy, brittle to tune |
| Keep inscribed-ellipse fallback | Reproduces rectangular logic and corner artifacts |
