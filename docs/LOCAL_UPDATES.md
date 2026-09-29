# Update the existing local application

## Normal operation

After PR #2 and this PR are merged into GitHub main, use the existing separate
GitHub checkout (Chris's `C:\Projects\Q-Trades`) and double-click
**Update Q-Trades.cmd**. A desktop shortcut to that file is sufficient.
The batch file calls one PowerShell script; it is not a wrapper around the retired
release manager. The running app remains in its original registered directory.

The script fetches the expected repository's **main** explicitly, fast-forwards
only, builds the dashboard, backs up application source, stops the existing paper
task, updates code/dependencies in that same application folder, restarts the task,
and checks the running commit and paper health. It discovers the folder from the
existing task, rather than asking the operator to repeat path setup.

A clean checkout is required. Divergent local commits, an unexpected origin, a main
without application files or a build failure stop before touching the running app.
No reset, force-pull, stash or branch switching is performed. The fetched commit,
not an unmerged development head, supplies the installed source.

## What is and is not copied

Only **src**, **scripts**, **apps/web**, and four root source/packaging files are
updated. Mirroring applies only to those code subdirectories, never a project root.
A dated source-only backup is retained under the original `data/update-backups/`.
Local edits to operating source are retained there, but main becomes the installed
source; normal development belongs in the separate GitHub checkout.

**data, configs, docs/evidence, the original .git metadata and Compose configuration
are not copied, deleted or restored.** Dependency/cache directories are excluded
from source mirroring. The existing database volume, paper history, model data and
credentials stay in place. No task action, task principal, desktop executable,
financial rule, account approval or risk profile is rewritten by the updater.
Do not start a code-editing or frozen qualification job during a manual update.

## Failure and retry

Download/build/backup failure: the operating code stays unchanged. A service that
will not stop is not overwritten; the updater never kills processes by guessed PID.
It also waits for the existing supervisor mutex before copying code.

Copy/dependency failure: the application is left stopped and the source backup is
reported. Resolve the displayed error and run the same updater again. It does not
pretend an old virtual environment was restored, reset a database, or automatically
roll financial history backward. Source backups are never pruned automatically.

Startup/health failure: the installed commit is reported but update success is not
claimed. The existing supervisor continues its normal recovery. Inspect its logs;
do not reset accounts. A later normal update uses the same batch file.

## Scope and acceptance

The old managed installer is archived at `archive/cp0-managed-updater-20260929`.
Its native acceptance problems are not bypassed to deploy that code: that driver,
its installation API/UI and its activation/checkpoint machinery are removed from
the active implementation. The newer original engine diagnostics remain preserved.

No operating workstation update has been executed by this change. GitHub main
must first contain the reviewed application; a push or CI pass is not deployment.
This command is manual. Automatic updates and paid inference are not enabled.

References: Git fetch/merge fast-forward semantics; Microsoft robocopy exit codes
(0-7 are nonfailure, 8+ failure) and Stop-ScheduledTask. Original local task and
runtime source were inspected before selecting this existing-folder approach.
