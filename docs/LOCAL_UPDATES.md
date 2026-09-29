# GitHub main to the local application

## Status: check and preparation implemented; activation not connected

GitHub `SAC-CS112-Randall-Christopher/Q-Trades` **main** is the authority for
accepted code. Local databases and retained research evidence remain the authority
for account and experiment history. A pushed branch or merged PR does not itself
change the executing Windows service.

This CP0 follow-up provides a main-only check, isolated release preparation, version
visibility in the app, a read-only Windows installation inspector, and explicit
support for keeping an existing runtime's data outside a new code release. It does
**not** register/repoint a task, stop/restart an operating worker, activate a release,
change the desktop executable, migrate a database, or enable automatic updates.
CP0 remains open until the native activation/recovery handoff is implemented and
verified on the actual Windows installation. Do not describe this PR as deployment.

## Operator-visible behavior

The **Code version & updates** panel shows the source commit captured at process
startup, whether the checkout was modified, the last successfully checked main
commit and check time, and the last update phase. **Check GitHub main** is an
explicit local-operator action; ordinary refreshes never call GitHub. Git runs off
the application event loop. No model call or signing credential is involved.

`GET /api/installation` is read-only and no-store. The check POST requires the same
local-operator header and same-origin validation as existing controls; duplicate
checks are throttled and the updater has an OS-released operation lock. Failed or
offline checks retain the last successful main identity without relabeling it as
fresh. Local startup does not require network access to GitHub. Missing local Git
leaves the source unidentified, rather than preventing the application from starting.

A source identity is not a health check or proof of trading correctness. The usual
paper-account panels retain reconciliation information. A prepared release is not
an installed release. The panel deliberately says activation is not connected.

## Registered installation identified

Chris supplied the actual task working directory:
`C:\Users\chris.t0\Documents\Codex\2026-09-27\we-are-starting-a-new-project`.
The task executable is that directory's `.venv\Scripts\pythonw.exe`. Native source
was inspected through the read-only mount; newer engine diagnostics and tests absent
from the ZIP have been preserved in this PR. See
[the source-preservation and native handoff record](reviews/cp0-local-updates/native-handoff.md).
This establishes the registered root and observed source, not current worker health.

The windowless host, supervisor, process/task identity checks and desktop launcher
now accept the existing runtime root separately from the release code directory.
The host forwards `--runtime-root` only for paper, never to the model service.
The supervisor retains the original Compose/data/log/PID location while running
Python from the chosen release. Existing default commands remain supported.
These are launch-path prerequisites: a native activation/rollback driver has **not**
been implemented or installed, and no task has been repointed by this PR.

## Inspect the actual Windows installation first

From this PR's source checkout in Windows PowerShell:

```powershell
.\scripts\Get-QTradesInstallation.ps1
```

This reads only the named `TradingResearch-Paper-20260927` task, its working
directory, expected startup-command identity, presence of the existing data files,
and the paper-port listener identity and current read-only health when ownership verifies. It does not read database passwords, enumerate
unrelated process command lines, alter a task, or restart a service. A listener PID
alone is explicitly **not** proof of ownership; executable, command, timestamp and parentage
are checked before the health request. Do not assume the runtime root is
`C:\Projects\Q-Trades` just because that is the Git checkout.

Health values are tri-state: `true` and `false` mean those Boolean values were
reported; `null` means the field was missing or invalid. `complete: false` and
`unknown_fields` identify incomplete inspection. JSON text is explicitly parsed;
an unusable response is unknown, never proof of a stopped or unbalanced account.
A successful HTTP request alone is not a healthy-account check. See
[the health correction and operator report](reviews/cp0-local-updates/health-inspection.md).

The shared `PaperStartupIdentity.ps1` contract fixes a source-confirmed mismatch:
the installed task writer supports the project `pythonw.exe` / `service_host.py`
host, while the old desktop-open script accepted only the older PowerShell action.
Both exact historical actions are recognized; foreign paths, arguments and multiple
actions remain rejected. This change is not installed on Windows by a Git push.

## Check and prepare from the operator's terminal

Python 3.12+, Git authenticated locally for this private repository, and Node/npm
are required. Do not paste credentials into chat or the repository. First verify
that the source import and this follow-up are actually merged into main. The
preparer refuses a main branch without the release contract.

After obtaining the real runtime root from the inspector, set `$runtimeRoot` to
that value; this is not a guessed or automatically created data directory:

```powershell
python .\scripts\qtrades_update.py check --runtime-root $runtimeRoot
python .\scripts\qtrades_update.py prepare --runtime-root $runtimeRoot `
  --releases "$env:LOCALAPPDATA\RandallAutomationWorks\QTrades\releases"
```

Preparation fetches the expected origin's `main`, pins the exact commit, and clones
a separate detached release. It never switches or resets the development checkout,
checks out a PR branch as accepted code, overwrites the running source folder, or
copies runtime data. Dirty/unexpected source checkouts, unsupported contracts,
tracked runtime/credential files, source symlinks, inadequate disk space, failed
commands, source/commit changes during a build and missing dashboard output stop
preparation. Pattern checks are not a universal secret-detection guarantee.

Each release has its own Python environment, pinned dependencies and compiled web
assets. Environments are built at their final paths, not moved afterwards. npm
installation disables dependency lifecycle scripts; the reviewed application build
still runs. A receipt records the selected commit/tree and dashboard asset hashes.
Modified prepared assets cannot claim a clean prepared identity. Failed preparations
and previous releases are retained, never pruned automatically. The running account
files, account permissions and funding are not mutated by either action.

`main-update-status.json` and the operation lock live in the existing runtime's
ignored `data/` directory. Receipts are small atomic file replacements. The dashboard
exposes only validated IDs/times and fixed messages, not paths, raw subprocess output,
credentials or arbitrary text inserted into those receipts.

### Existing runtime storage support

`trading serve --experiment --runtime-root <existing-project>` uses that project's
existing monitor database, paper database settings, application configuration and
research evidence while the code and compiled UI come from the selected code
working directory. Missing monitor/history settings fail instead of silently
starting a new account. The paper ledger is read and reconciled before application
startup; existing collector and exclusive financial-writer protections still apply.

This option is a prerequisite for managed activation, **not an instruction to launch
a second service beside the running worker**. Do not use it to bypass the pending
native task/worker ownership checks. No new-model or frozen-policy activation is
implied by a code update.

## Remaining CP0 native activation work

1. Inspect the actual task, desktop launcher, worker identity, source drift and data
   ownership; retain any local-only work and active/frozen research artifacts.
2. Bind a stable, project-owned local launcher to a verified prepared release while
   retaining the old runtime data/configuration/evidence roots and model runtime.
3. Prepare before interruption; perform an explicitly authorized, identity-checked
   cutover without duplicate writers or pulling into an executing worker.
4. Verify schema compatibility and before/after financial history, reservations,
   balances, positions, policies and reconciliation; show the actual active commit
   and successful health verification in the UI.
5. Exercise interruption/restart, failed activation and compatible code rollback.
   Never restore an old database over newer trades merely to roll code back.
6. Demonstrate the normal desktop launch and subsequent main update on Windows.
   Auto-activation remains disabled unless separately authorized as a policy.

No `activate` CLI action, HTTP activation route, background GitHub poller or task
rewriter is included in this preparation PR. Those missing operations are not
reported as completed merely because preparation or Linux tests passed.

## References checked September 28, 2026

- Git fetch semantics: https://git-scm.com/docs/git-fetch
- Isolated working trees: https://git-scm.com/docs/git-worktree
- Virtual environments and non-portability: https://docs.python.org/3/library/venv.html
- Windows task inspection: https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/get-scheduledtask
- Windows task updates: https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/set-scheduledtask
