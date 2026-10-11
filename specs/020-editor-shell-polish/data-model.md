# Data Model: Editor Shell v2 (UI state only)

No server document changes.

| Field | Location | Notes |
|-------|----------|-------|
| `theme` | settings.json | dark / light / system — unchanged |
| `ui_scale` | settings.json | 100–150 — drives `--ui-scale` |
| `is-pages-collapsed` | `document.body` class | session UI only |
| `is-inspector-collapsed` | `document.body` class | session UI only |
| brush size | existing viewer state | shown in dock popover |
| `tokens.json` | generated artifact | mirror of CSS custom properties |
