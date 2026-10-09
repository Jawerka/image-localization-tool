# Data Model notes

Uses existing `PageDocument.warnings: list[str]`. No new persisted fields.

Transient: `LamaInpainter.last_warnings` cleared per `inpaint` call.
