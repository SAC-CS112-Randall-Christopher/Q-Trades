# Native installation identified; local work preserved

Chris supplied the registered Windows task action in the conversation:

- Task: `TradingResearch-Paper-20260927`
- Working directory: `C:\Users\chris.t0\Documents\Codex\2026-09-27\we-are-starting-a-new-project`
- Executable: that directory's `.venv\Scripts\pythonw.exe`.

This is **registration evidence**, not an independent current process/health check.
The new `C:\Projects\Q-Trades` checkout is not this task's operating directory.
The corresponding named project was inspected through the existing read-only Codex
mount. Its Git directory has no committed HEAD; no history was invented or changed.

## Newer native work that must not be lost

Compared with the original import, 92 files in the scoped runtime/test/configuration
comparison matched byte-for-byte. Two existing files differed:
`src/trading/tiered_runtime.py` and `tests/test_streaming.py`.
Two new files were present: `src/trading/engine_diagnostics.py` and
`tests/test_engine_diagnostics.py`. The extra import-publication script is absent
from the native runtime by design. The frontend entry HTML was checked separately
and its content also matches. This is a scoped comparison, not a statement that
all local documentation, evidence, dependencies and generated files are identical.

All four newer diagnostic files were reviewed and copied byte-for-byte into this
PR. Their fingerprints are retained in `native-source-preservation.json`. Changes
record engine stage/CPU/wall timing and bounded, coalesced resource notices; the
existing resource thresholds, trading rules and financial accounting are unchanged.

## Launch-path implementation

The windowless host, paper supervisor, process-ownership checks, desktop launcher
source and launcher builder now accept an explicit existing runtime root. Code and
Python come from the selected release; Compose startup, log/PID files, application
configuration and financial/research storage stay in the original runtime folder.
The model service retains its existing command and rejects a paper-runtime redirect.
No task registration or activation driver is installed by these source changes.

The inspection helper validates the exact task action and optional expected data
root, then verifies the paper listener's executable, command, timestamp receipt and
parentage. Only a verified listener receives the read-only status request. It reports
unavailable health, stale data and failed reconciliation without starting/stopping
anything. Unknown ownership remains explicit, not inferred from a port number.

## Verification of this follow-up

- Full suite: **266 passed, six native-Windows skips**, one existing Starlette warning.
  These overlap the earlier 248/261-test runs; totals must not be added.
- Ruff, strict mypy (36 modules), Python compilation, TypeScript and Vite build passed.
- Ten inspector cases execute the actual PowerShell script with mocked OS inputs:
  healthy, no listener, public listener, reused PID, foreign worker/task, wrong root,
  unavailable health, stale paper and failed reconciliation. No real service calls.
- Three Python command-routing cases and two PowerShell managed-handoff cases pass.
  The supervisor case uses disposable code/data directories, a unique test mutex,
  mocked Docker/process operations and a retained-file sentinel; it is not deployment.
- PowerShell 7.6.6 on Linux was used for those script tests. Its official release
  checksum was verified. The six existing Windows-native checks still need execution.

Six changed PowerShell files and the C# launcher passed syntax parsing. This is not
native .NET Framework compilation or evidence of actual task activation. Existing
native files, account data, process registration, model runtime and frozen research
receipts were not modified. The currently running code must be inspected again at
any authorized cutover; this source snapshot is not permanent deployment permission.

Next native verification uses a separate development worktree, the existing Python
interpreter, isolated startup/inspector tests, a build-only launcher check (without
`-InstallDesktop`) and `Get-QTradesInstallation.ps1 -ExpectedRuntimeRoot ...`.
The actual activation/recovery driver, approved main merge, controlled task cutover,
and before/after financial verification remain required before CP0 can be closed.
