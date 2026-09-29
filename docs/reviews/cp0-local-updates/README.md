# CP0 simplification — September 29, 2026

Chris explicitly requested a simple batch updater rather than a new installer.
The previous implementation/evidence is preserved at commit
`88c5d3a851c05195f34a47f0d396f34e495e74f7` and branch
`archive/cp0-managed-updater-20260929`; nothing was force-pushed or erased from history.

The current design updates the original installed app folder using the existing
GitHub checkout and Windows task. The managed-release backend, installation UI,
activation state machine, financial checkpoint hashing, task rewriting and rollback
driver are removed, not hidden behind another wrapper. The code backup is not a
database backup. Important failures stop rather than silently claiming deployment.

The four original newer engine diagnostic files remain byte-preserved relative to
the native source capture; their receipt is `native-source-preservation.json`.
The original Windows app and the CP1 worktree have not been changed.

Current verification is recorded in the PR after executing the relevant checks.
Old 335/354 counts and Windows acceptance belong to the retired source and must not
be reused as evidence of this implementation. No native application cutover yet.
