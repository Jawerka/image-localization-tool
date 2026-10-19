# Data Model: Linux LAN Bootstrap and Safe Updates

## Release metadata

- `version`: required dotted application version; validated against a conservative numeric version pattern.
- `platform`: required `linux-x64` identifier.
- `executable`: expected packaged sidecar filename.

Metadata is written into the release bundle by CI. It is descriptive and does not grant archive paths permission to escape the staging directory.

## Filesystem layout

```text
<root>/
├── current -> releases/<version>
├── previous -> releases/<version>
├── .deployment.lock
├── releases/<version>/      # immutable application files
└── shared/
    ├── data/                # projects, settings, cache, logs, tokens
    ├── models/              # downloaded model assets
    ├── runtime/             # runtime packs
    └── components/          # versioned OCR/font component store
```

The active release may include links named `data`, `models`, and `runtime`; the systemd unit also sets explicit application path variables. Shared directories are never removed by install, update, or rollback.

## State transitions

```text
candidate -> validated -> staged -> active-pending-health -> active
                                      └─ health failure -> previous-active
```

The `previous` pointer identifies the last known healthy release. A successful update advances it before activation. A failed candidate remains available for diagnosis but is not active.
