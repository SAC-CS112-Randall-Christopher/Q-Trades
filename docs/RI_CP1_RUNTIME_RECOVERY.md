# RI-CP1: preserve the installed model-task owner during recovery

This source repair supports issue [#48](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/48).
It does not complete the real selected-4B research loop or authorize a restart.

## Observed boundary

The October 4 read-only baseline located one registered model task,
`TradingResearch-Models-20260928`, in `Ready` state. Its executable and working
directory matched the installed application, and its exact action was the local
windowless Python running `service_host_v2.py --kind models --runtime-profile
CpuElastic`. This is the observed installed action; current main still ships the
legacy host. A subsequent file check found that the registered current host was
absent. No replacement was located in the inspected Q-Trades worktrees or the
Lab's recorded resource-repair source. The dedicated port 11435
had no listener; the retained runtime receipt reported `failed`. A registered
task is not a running model service.

Both existing runtime helpers recognized only the earlier `service_host.py`
action. A native, disposable reproduction using copied unmodified helpers and
mocked Windows operations rejected the installed action as a different owner
before any dispatch. The two expected recovery tests failed in that reproduction.
No live scheduled task or process was targeted.

## Bounded correction

`Install-ResearchRuntime.ps1` and `Stop-ResearchRuntime.ps1` recognize the exact
legacy and current model-host actions, with their existing two CPU profiles.
Executable, working directory, task action count, model kind and full arguments
still determine ownership. Foreign paths, additional arguments and unsupported
profiles remain rejected.

The install helper prefers the current host when present and preserves an
already matching action without registration or downgrade. Idle legacy migration
retains the existing running-task/listener refusal. Missing host files fail before
dispatch; an existing current-host task is never silently downgraded merely
because its host file is unavailable. The explicit `-RecoverMissingHost` option
allows an operator-authorized recovery of that exact owned, idle action to the
existing shipped host, with an additional active-research-job refusal. Running
tasks and occupied model ports still prevent any re-registration. It does not
change the registered CPU profile as part of missing-host recovery. It does not
restore or claim equivalence to an unavailable former host. The stop helper
retains active-job, resident-model,
origin, process-parent/lifetime and remaining-listener checks, and preserves the
previous runtime receipt. Neither helper changes inference admission, model
policy, CPU limits, GPU use or financial authority.

## Verification and limits

The new `tests/test_model_runtime_task_ownership.py` executes copied real
PowerShell helpers in disposable directories. All task, process and HTTP
operations are mocked, and Windows module autoload is disabled. It verifies
both CPU profiles, legacy compatibility, no task rewrite for the current host,
foreign ownership, live-work preservation, reused process IDs, missing hosts,
remaining-listener failure, explicit missing-host recovery and retained previous
state. It is included in the
hosted Windows acceptance selection.

The final focused native suite passed 75 tests with no skips on Windows
PowerShell 5.1 / CPython 3.12.10, including 34 new task-ownership/recovery cases.
Ruff passed; strict mypy passed for 93 source files; dashboard type checking and
build passed. The earlier two-test unmodified reproduction failed as expected,
and an initial test-driver lint failure was corrected. These are separate from
the draft's exact-head hosted result.

A read-only preservation check verified 129 protected private artifacts, the
unchanged installed 4B manifest/blobs, v2 alias, configuration, storage identity
and 400/100 decimal GB allowances. The installed application remained at
`5d7bf356`, with no dedicated model listener, current role policy or qualification.
No live task, worker or operating account was changed for this repair.

Starting the fixture task deliberately leaves its runtime receipt `failed`:
task dispatch alone is not runtime readiness. These tests establish ownership
and recovery behavior, not actual inference, role qualification, installed
acceptance or trading value. The exact verification head and counts are recorded
in the draft PR; private failed receipts and preservation hashes remain private.

## Existing operator path after separate authorization

After the reviewed repair has been merged and installed through the existing
updater, use the existing helper from the verified installed application root:

```powershell
& .\scripts\Install-ResearchRuntime.ps1 -RuntimeProfile CpuElastic
```

If the verified task still points to the absent host, the explicit recovery
command, after separately approving that action, is:

```powershell
& .\scripts\Install-ResearchRuntime.ps1 -RuntimeProfile CpuElastic -RecoverMissingHost
```

Retain the original action/runtime receipts privately before this authorized
reconciliation. This selects the existing shipped supervisor rather than
inventing or downloading a replacement. Before any bounded selected-4B
development request, verify the new runtime receipt, original task/process
ownership, loopback listener, runtime/model/template identity, measured CPU-only
placement and continued paper health. Missing or failed verification remains a
blocker. Preserve the original failed receipt; do not reuse its stale PIDs.

Where stopping is separately authorized and the helper verifies no active job or
resident model, the existing path is:

```powershell
& .\scripts\Stop-ResearchRuntime.ps1
```

The unchanged whole-work resource guard and current role qualification contract
remain applicable. Role qualification does not enable operating research. The
October 4 baseline had no current role policy or qualification; no 4B request
was dispatched. The real hypothesis, numerical experiment, independent review,
paper comparison, genuine outcome maturity and follow-up remain open.

Do not reinstall prior rollouts, activate research, convert the v2 adapter,
repeat CP24/14B work, train weights or change protected workloads to make this
recovery appear complete. Existing drafts #49-52 remain separate source slices.
