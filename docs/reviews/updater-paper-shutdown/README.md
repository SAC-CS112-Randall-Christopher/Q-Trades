# CP0 native shutdown repair — September 29, 2026

The first authorized native update of merged revision 66fb978 stopped before
replacing application files: stopping the scheduled host left its windowless
PowerShell supervisor, venv launcher and base-interpreter paper worker running.
The existing updater correctly refused to copy over a listening application. Its
failed transcript and source backup remain private on this workstation.

The repair keeps the existing batch/manual update flow and registered task.
Immediately before task shutdown, it captures only the installed runtime's paper
supervisor, launcher and verified immediate worker. PID records are combined with
creation times, exact executable/command identity and the existing ownership
helpers. Model/GIS processes and generic process-name matching are excluded.

After stopping the scheduled task, the updater closes those verified descendants,
supervisor first to prevent a relaunch. Each process handle is pinned and its
identity checked again before termination. Missing processes need no action;
changed identities fail closed. The existing task/port/mutex checks still have to
pass before copying code. Private configuration and account data remain outside
the source copy.

## Verification

The full local PostgreSQL suite passed **389 tests, no skips, in 85.99 seconds**;
lint passed and strict typing passed for 47 source files. The seven added Windows
checks include a real disposable supervisor/venv/base-interpreter tree. The
native test verifies all three owned processes stop, an unrelated real process
survives, a false PID record cannot grant ownership, and a changed creation time
cannot authorize a stop. No network, financial store or model service is started
by that fixture.

The first focused run was **one failed, 32 passed**: the new test tried to modify
a read-only CIM property. That receipt is retained in `initial-focused-tests.txt`.
The fixture now copies its snapshot before changing the lifetime; the corrected
native checks and complete suite pass. This does not relabel the earlier run.

Hosted run 36650027797 then reported **one failed, 164 passed, 32 database skips**.
The disposable fixture copied `sys.executable`, which is a venv redirector locally
but a base interpreter on the runner; the latter produced a two-process tree.
The fixture now creates a real virtual environment without pip/network access on
both hosts. The updater's process-identity and shutdown code did not change for
this fixture correction. The hosted red log remains in the review evidence.

The actual installed runtime's three still-running paper processes were separately
verified read-only against their executable, command and PID-file creation time.
Hosted exact-head checks, merge, final-main checks and a successful native updater
retry must still be observed before claiming the application is updated. Financial
prefix hashes, original funding/policy comparisons and update logs stay private.
