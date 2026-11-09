# Data model
Job: id, createdAt, deadlineAt, stage, errorCode, status. Deadline persisted; legacy state receives one finite migration.
SourceResult: relative filename identity, source hash/dimensions, engine/warnings, execution status, artifacts, review status. No stem collisions.
DeploymentPlan: artifact and target absolute paths, artifact hashes, target precondition hashes, explicit changes/deletions, protected paths, required/free bytes. Apply rejects changed inputs.
Backup: original managed files and verified hashes; newly created files recorded for rollback; unrelated data retained.
