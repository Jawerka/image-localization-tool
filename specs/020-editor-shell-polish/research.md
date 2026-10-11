# Research: Editor Shell v2 Port

## Decision: Live SSOT for tokens

**Choice**: After merge, `web/css/tokens.css` is runtime SSOT; `scripts/export_tokens.py` → `web/tokens.json`. `next/tokens-v2.css` remains design reference only.

**Rationale**: Flutter later must not scrape mockups; live CSS already drives the app.

## Decision: Scale via `--ui-scale`

**Choice**: Translate v2 fixed metrics to `calc(Npx * var(--ui-scale))`. Do not use mockup `zoom` in live UI.

**Rationale**: Settings already persist `ui_scale` 100–150; e2e and appearance path expect `--ui-scale`.

## Decision: Icons in `icons.svg`

**Choice**: Add panel/grip/fit-width/more-h symbols to `web/icons/icons.svg`. No `sprite.js` in live tree.

**Rationale**: Live UI is served over HTTP; external `<use href="icons/icons.svg#id">` works.

## Industry patterns (URL-backed)

| Pattern | Source | Mapping |
|---------|--------|---------|
| Four zones | [OmniGraffle](https://support.omnigroup.com/documentation/omnigraffle/mac/7.11/en/); [Lopaka](https://lopaka.app/pages/docs/editor-overview) | pages / scene / inspector |
| Canvas first | [pen.dev](https://docs.pen.dev/core-concepts/pencil-interface) | scene + floating sheet |
| Contextual tools | [FlueraCanvas](https://github.com/Lorencoshametaj/fluera_canvas); [fldraw](https://github.com/fldraw/fldraw/) | floating dock |
| Zoom/pan | [pen.dev](https://docs.pen.dev/core-concepts/pencil-interface) | keep viewer.js / keys.js |

## Parity map (keys / gestures)

| Action | Binding | Owner |
|--------|---------|-------|
| Fit | Ctrl+0 | keys.js → zoom fit |
| 100% | Ctrl+1 | keys.js |
| Pan | Space+drag | viewer.js |
| Tools | V/R/B/P/H | keys.js |
| Layers views | 1/2/3 | keys.js |
| Undo/redo | Ctrl+Z / Ctrl+Y | keys.js; typing guard |
| Brush size | dock popover + range | shell_chrome + viewer |
| Panel toggle | dock/header buttons | shell_chrome `is-pages-collapsed` / `is-inspector-collapsed` |
| Done chip | top float | apply_chip.js (unchanged contract) |

## Screen → module map

| next screen | Live modules |
|-------------|--------------|
| main-editor | index.html shell, editor.css, shell-v2.css, viewer.js, inspector.js |
| main-empty | empty drop in viewer |
| main-batch | pages.js, batch-panel.js |
| settings/dialogs/… | unchanged panels; chrome tokens only if shared |

## data-role policy

**Preserve** all roles listed in `contracts/data-role.md`. Relocate nodes if needed but keep attributes. Update tests only if a role must move to a duplicate control (e.g. settings icon still `data-role='settings'`).
