# CP0 explicit activation and recovery implementation

Implementation: `77fd2bcbe57885f10202da689ea64af8c16aeab3`.
Subsequent preparation-label correction: `e6297206ca227ca5c38a6c7649cee10940ba79aa`.
Base before this work: `81824a6cbe6e2381bcb01a8c5110294b5180521f`.

## Outcome and status

The existing PR now contains the actual activation/recovery driver, not only an
installation inspector or release preparer. The supported Windows entry point is
`scripts/Update-QTrades.ps1`: Verify, Check, Prepare, Activate, Recover. Native
activation/recovery require explicit `-Apply`. GitHub main remains the accepted
code authority; no unmerged release is eligible. The running financial database
and retained research remain in the original runtime directory.

**No native cutover was performed.** Neither PR was merged; no operating Windows
task, service, desktop executable, account, policy or model runtime was changed.
Automatic updates remain disabled. CP0 is not closed until the new driver is
accepted on Windows and an explicitly authorized main release is installed and
verified through the actual desktop application.

## Implemented and verified in isolation

- The updater writes a recovery record before any native stop/configuration action.
  Task principal, triggers and settings are preserved; only its selected action and
  enabled status are managed. Process identities/handles are verified, not guessed
  from a PID alone. Foreign tasks, listeners and reused IDs are rejected.
- The API holds the financial writer locks and compares a complete saved account
  checkpoint before any collector or financial worker is scheduled. Missing history
  does not create a fresh account; absent historical options state is not initialized.
  Existing pending orders and balances are preserved in an actual PostgreSQL/API test.
- Read-only repeatable-read checkpoints cover account state, revision, event count/
  last ID and ordered financial journal hashes. They do not claim to hash every raw
  market/evidence payload. Writer-exclusion probes close their connections on failure.
- Recovery recaptures current financial history, including trades made after a new
  worker started, instead of restoring an old database. Original source/configuration
  drift, differing core financial modules or unverified desktop replacements stop
  automatic recovery. Financial comparison normalizes CRLF only; other changes are
  not treated as equivalent. No schema/policy downgrade is implemented.
- The driver compiles/backups the desktop launcher before interruption and installs
  it only after account/startup/version/health checks pass. Restoration is hash-checked
  and idempotent; unrelated or modified files are preserved.
- Main rechecks retain a prepared release at the same commit. Repeated activation
  of the already running identical release does not restart it. Archive-write failure
  cannot publish a successful phase. Failure receipts remain available for recovery.
- The UI reports installation/recovery state separately from current paper-account
  health. No HTTP activation or recovery endpoint exists. The paper event loop never
  waits for a model or a GitHub update check.

## Executed evidence

**Final full suite at e629720: 334 passed, six native-Windows skips, one existing
Starlette TestClient warning, 46.28 seconds.** See `activation-pytest.txt`.
Ruff, strict mypy for 38 source modules, Python compilation, TypeScript and Vite
production build passed. The earlier 282/325/331/334 totals overlap; never add them.

New coverage includes 26 activation/recovery orchestration cases using real
throwaway Git repositories and simulated native operations; ten read-only
PostgreSQL/API startup-checkpoint cases; eleven actual PowerShell-driver cases
with mocked OS responses; four actual desktop copy/restore cases using synthetic
executables in temporary directories; and one main-recheck preservation test.
No synthetic executable is run. Windows task commands are mocked and the test
supervisor mutex uses a unique name, never the operating mutex.

The native driver and one-command wrapper also passed PowerShell syntax parsing.
PowerShell execution here uses the previously checksum-verified 7.6.6 Linux runtime;
this does not establish Windows 5.1 scheduler/handle behavior. Database integration
uses the dedicated disposable PostgreSQL 17 cluster, not the operating Windows
PostgreSQL 18 account. No original account data was injected into these tests.

### Real build rehearsal

`activation-release-build.json` records the actual default builder at 77fd2bc:
new venv, pinned Python packages, installed application wheel, pip check, locked
npm dependencies, TypeScript/Vite, API imports, imports of the new activation and
startup-guard modules from the installed wheel, source and asset verification.
The run took 23.625 seconds. A disposable local bare repository represented main;
GitHub main was not modified. The synthetic runtime sentinel remained unchanged.
The subsequent e629720 change labels a prepared release `not_activated` instead of
`not_connected`; its targeted 59-case check and final full suite passed. The older
rehearsal receipt is retained as produced, not relabeled or regraded.

### Actual browser/API workflow

`activation-browser.json` records the compiled app running on loopback 18871 with
all market and financial workers disabled. Its process-start identity was clean
77fd2bc. Actual GitHub main checking correctly reported the original README-only
main, with no application release. Status failure, periodic recovery without a
reload, and visible check failure passed with zero page errors/non-loopback requests.

Synthetic saved activation records were supplied only to the disposable browser
runtime to exercise the real API projection and UI: verified installation and
recovery-required states rendered correctly. Desktop 1440px and phone 360px layouts
had no horizontal document overflow. The accompanying screenshots are these
**synthetic recovery states**, not operating-account failures or a Windows cutover.
The QA server was separate from the operating application's port and account data.

## Remaining native acceptance

Chris's previously reported 21 Windows passes and build-only launcher compilation
apply to 943c574, not this new driver. His direct healthy paper snapshot at revision
204325 remains prior operator evidence, not an assumed current cutover precondition.

Run the new Verify command from an isolated Windows checkout. Preserve any failures.
Then, following explicit approval, merge the import/update PRs, prepare the exact
main release, run activation preflight, apply the controlled cutover, and retain
startup/account/active-commit/desktop verification. Exercise compatible recovery
with disposable native state before relying on it for the operating installation.
Keep all source versions, old launcher and financial history; never reset the data.

Primary implementation references checked September 28, 2026:
- https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/set-scheduledtask
- https://www.postgresql.org/docs/current/transaction-iso.html
- https://docs.python.org/3/library/subprocess.html
