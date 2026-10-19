# Contract: Windows release metadata

The portable bundle must include a UTF-8 `release.json` object:

```json
{
  "schema": 1,
  "version": "1.2.3",
  "platform": "windows-x64",
  "host": "desktop/ImageLocalizationTool.exe",
  "sidecar": "sidecar/ImageLocalizationTool.exe",
  "web": "web/index.html"
}
```

`schema`, `version`, `platform`, and all three relative entry paths are required. Version uses 2–4 numeric dot-separated components. The updater rejects other platforms, path traversal, missing entries, and symbolic-link/reparse-point entry paths before activation.
