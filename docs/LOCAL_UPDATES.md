# GitHub main to the local application

## Status

The implementation now includes **check, prepare, explicit activation, and recovery**.
GitHub main supplies accepted code; the workstation retains the existing accounts,
configuration and research evidence. No Git push or merge itself deploys anything.
Automatic activation remains disabled. The new native activation/recovery driver
has been tested using disposable Git/database state and mocked Windows APIs, not
applied to the operating Windows installation. CP0 remains open until that native
acceptance and the authorized first cutover are observed.

The operating data root reported by Chris is:
`C:\Users\chris.t0\Documents\Codex\2026-09-27\we-are-starting-a-new-project`.
`C:\Projects\Q-Trades` is a separate development checkout. Never copy runtime
credentials or databases into Git, or pull source into an executing worker.

## One supported Windows entry point

Use the current reviewed source checkout, not the operating source directory. Set
`$runtime` to the registered existing root above. The helper reuses its existing
Python interpreter to operate the updater; each prepared release has its own new
environment. Git authentication stays local. No token should be pasted into chat.

```powershell
.\scripts\Update-QTrades.ps1 -Action Verify -RuntimeRoot $runtime
.\scripts\Update-QTrades.ps1 -Action Check -RuntimeRoot $runtime
.\scripts\Update-QTrades.ps1 -Action Prepare -RuntimeRoot $runtime
```

Verify runs the read-only installation inspector, isolated tests and a build-only
launcher compilation. It does not install the executable or change startup tasks.
Prepare requires the application/update changes to be merged into main; it creates
an isolated exact-main release under the user's LocalAppData QTrades releases folder.
An unmerged branch cannot become accepted code by supplying its commit manually.
A restricted single-branch clone is supported: fetches name main explicitly.

After reviewing the prepared release and approving the local cutover:

```powershell
.\scripts\Update-QTrades.ps1 -Action Activate -RuntimeRoot $runtime
# The first command is a preflight. The next command applies the approved cutover.
.\scripts\Update-QTrades.ps1 -Action Activate -RuntimeRoot $runtime -Apply
```

Without `-Apply`, activation/recovery do not mutate tasks, processes or the desktop.
The exact prepared path/commit come from the last successful local preparation
receipt and are verified again against Git and main. A main check at the same
commit does not lose that prepared release. Changed source, unsupported releases,
unverified ownership, incomplete health or unresolved earlier updates stop the path.

## Activation order and data protection

1. Revalidate release source, prepared web assets, main membership, installed-task
   identity and current account reconciliation. Record the previous source hashes,
   original task action/settings signature, configuration binding and desktop hash.
   Compile the new launcher and preserve a verified copy of the old launcher before
   interrupting anything. A foreign desktop executable is not overwritten.
2. Persist a recovery receipt **before** native side effects. Disable and stop only
   the named paper task. Retain OS process handles after verifying executable,
   command, creation-time receipt and parentage; stop only those verified processes.
   Refuse a remaining listener, supervisor mutex or financial writer. PID reuse is
   not authority to terminate an unrelated process. The model task is never changed.
3. Once writers are stopped, read a fresh, consistent financial checkpoint. It
   includes full state hashes (balances, positions, reservations and policies),
   event counts/last IDs and the ordered financial-journal digest. It includes any
   trades that naturally committed during preflight. Configuration and database
   bindings must remain unchanged. Nothing restores, deletes or resets a database.
4. Change only the existing task action to the prepared release's windowless host,
   retaining its principal, triggers/settings and original runtime data root.
   Before scheduling any market/financial worker, the new application holds both
   financial writer locks and verifies the exact saved checkpoint and source ID.
   Unknown/mismatched state prevents worker startup; missing history never creates
   a replacement account. Absent historical options state is not newly initialized.
5. Start the selected task and require owned-process identity, an acknowledgment of
   checkpoint preservation, the expected process-start commit and current paper
   health/reconciliation. Historical options replay has no live `stale` flag: its
   running worker and balanced ledger are required, not fresh live options data.
6. Install the verified new desktop launcher without overwriting a file changed
   since preflight. Record successful installation and verification time. Repeating
   activation for an already running identical release does not restart it.

Updates can briefly interrupt market observation. Normal gap handling remains in
force; no trades are invented during an outage. Checkpoints do not copy raw market
history or credentials into Git. Event counts and a journal digest are not described
as a cryptographic digest of every raw market-data/evidence row.

The existing monitor database, paper database configuration, Compose volume, logs,
PID files, and research evidence remain at the original runtime root. Code/Python
and compiled UI come from the prepared release. A software update is not permission
to change frozen financial policies, refill losing accounts, or enable live trading.

## Recovery and rollback

```powershell
.\scripts\Update-QTrades.ps1 -Action Recover -RuntimeRoot $runtime
.\scripts\Update-QTrades.ps1 -Action Recover -RuntimeRoot $runtime -Apply
```

A failed or interrupted update leaves an explicit recovery receipt, never a success
claim. Recovery re-inspects the actual task/worker rather than assuming a timeout
meant nothing happened. It stops only the verified installation, captures the
**current** account checkpoint, restores the previous verified task/launcher and
checks health again. Newly recorded trades are not rolled back with the code.
Previous code and failed/prepared releases are retained. No automatic pruning.

Before interruption, this initial activation contract rejects differing core financial
modules rather than installing a change with no established recovery path.
The recovery contract also refuses changed previous source, changed runtime
configuration, an unrelated desktop replacement, or differing core financial
modules. It supplies no schema/policy downgrade or database-restore facility. A
future checkpoint changing those financial modules needs an explicit tested
compatibility/recovery policy; do not bypass the refusal to make deployment pass.
A repeated successful recovery is idempotent. If process identity, disk, files or
compatibility cannot be established, preserve the receipt and inspect the failure.
No blind force-kill, force-push, clean/reset, volume deletion or restore is a remedy.

`local-activation.json` and per-phase records live in ignored local `data/` storage.
They are operational evidence, not a second financial ledger. The same updater lock
serializes check/preparation/activation/recovery. A crashed updater leaves enough
information for explicit recovery. A managed worker cannot start through an
incomplete update without the required account/source checkpoint.

## UI and offline behavior

The Code version & updates panel shows source captured at process startup, last
checked main, activation/recovery status and last verified installation time.
Missing/invalid inspection fields remain unknown, not false financial failures.
Ordinary polling is read-only and never contacts GitHub. Check GitHub main is an
explicit same-origin/local-operator action running off the financial event loop.
There is no HTTP activation or recovery route. Manual terminal activation is the
only installation path in this checkpoint. Local startup does not require GitHub
availability; already installed code keeps operating through a GitHub outage.

The last successful installation check is historical evidence, not a continuously
healthy-account assertion. Current paper panels show live freshness and financial
reconciliation separately. Unavailable and recovery-needed states remain visible.

## Remaining acceptance before closing CP0

- Execute the new driver tests on Windows (earlier 21 native passes predate it).
- After explicit merge/cutover approval, prepare and activate the approved main
  release on the actual workstation. Retain the before/startup/after receipts.
- Verify the normal desktop launch, correct process-start commit, retained accounts,
  subsequent main-update path, and compatible recovery on native Windows.
- Do not start CP1 activation or autonomous research merely because Linux tests pass.

## Primary references

Checked September 28, 2026: Microsoft Learn `Set-ScheduledTask`,
`Disable-ScheduledTask`, and `.NET Process.Kill`; Python subprocess documentation;
PostgreSQL transaction isolation / repeatable-read documentation. Task-definition
changes do not replace an already running task instance. Native acceptance remains
necessary; Linux mocks are not a substitute for Windows process behavior.
