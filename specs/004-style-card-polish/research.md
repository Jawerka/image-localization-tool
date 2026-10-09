# Research: 004-style-card-polish

## Font faces in `<select>`

Browsers allow `font-family` on `<option>` when `@font-face` is registered. Need font bytes URL → add `/api/fonts/{id}/file` mirroring preview auth/path lookup via `find_font`.

## Flag vs wave

- `wave`: existing bi-axial sine (`_map_wave`).
- `flag`: only `map_y -= amp * sin(phase_x)` (fabric along horizontal). Distinct kind string `flag` in document warp.

## Project styles

API already returns `{ styles: [{ name, style }] }`. Apply copies `style` dict onto region.style (shallow + warp object replace). UI: compact buttons in `<details class="region-card__styles">`.
