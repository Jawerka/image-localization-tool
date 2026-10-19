# Release Metadata Contract

Each packaged Linux server root contains `release.json`:

```json
{
  "schema": 1,
  "version": "1.0.2",
  "platform": "linux-x64",
  "executable": "ImageLocalizationTool"
}
```

Rules:

- `schema` is the integer `1`.
- `version` is a dotted numeric version and matches the release directory name.
- `platform` must be exactly `linux-x64`.
- `executable` must be exactly `ImageLocalizationTool` and the file must exist and be executable.
- Installer and updater reject missing, malformed, or unsupported metadata before activating the release.
- Metadata does not replace archive checksum verification performed by the release download workflow.
