# Financial monitoring correctness follow-up — October 5, 2026

The R63-1 recovery follow-up below records source correction
`5c8eca9ab128dfbc242f8ea87d2c3aaac89b2443`. Earlier C60 receipts and clear reviews
at `932c2b7` remain historical evidence; they did not establish R63-1 recovery.
Final published-head hosted results are recorded in
[draft PR #63](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/pull/63).

Source follow-up to merged #60, based on main `fca588586`. This implements the
three C60 findings while preserving #60's sound cooldown/topology changes and
#62's original release receipt. It is not a rollout or trained-model acceptance.
PR #61 subsequently merged to main at `dcf7ccbb1`; this branch incorporates its
memory/reviewer owner and independent CI job. Its model/installed finish line
remains separate from these monitoring repairs.

## Ordered request and acceptance checklist

1. [x] **C60-1: completed negative reconciliation survives ancillary failures.**
   `FinancialReadback` completes its repeatable-read/read-only safety transaction
   first. Its audit receipt includes the captured revision and observation time,
   and reaches the runtime before optional history/storage queries. A confirmed
   negative skips those refreshes and wakes the existing financial supervisor.
   Query/connection failure before completion supplies no passing audit. Optional
   refresh errors retain the completed audit and previous history; they block
   optional research conservatively and do not stop financial work by themselves.
   The older inline implementation shared some of the original ordering weakness.
2. [x] **C60-2: current monitoring and last verified result agree across surfaces.**
   One derived `journal_status()` supplies snapshot, health, guard and notices.
   Pending, balanced, expired, unavailable and confirmed-imbalanced are distinct.
   Last completed audit time/revision/result remain unchanged during an outage or
   expiry. Health's `journal_balanced` describes a currently available audit;
   `journal_last_balanced` retains the historical result. The ordinary Accounts
   interface's **Original Tier 3 trial and review history** shows both meanings,
   with amber unknown/unavailable, green current-balanced and red imbalance.
   The complete producer batch passes the existing notice validator and registry,
   including current/historical audit facts, critical imbalance and confirmed
   recovery. Existing recording/input/resource notices continue to advance in the
   same atomic batch; invalid conditions remain rejected.
3. [x] **C60-3: cancellation and drainage have a fixed operation lifecycle.**
   The existing authenticated read-only reader runs in one owned spawned child,
   using the same `PaperStore` queries. The financial connection/owner lock are
   never inherited; credentials travel over private local IPC, not command-line
   arguments. One request at a time, 15-second operation budget including startup
   and dispatch, 1-second bounded
   `cancel_safe` request inside a fixed four-second drain, then at most one second
   to terminate that exact original child handle. Repeated cancellation does not
   extend the deadline. Normal closure follows worker completion; a stuck client
   thread is contained by child termination, without closing its live connection
   from another thread or terminating a looked-up database backend. Escalation is
   exposed in `last_shutdown` and logged. Termination failure is explicit, retains
   ownership and stops continuation. Receipts have a two-MiB ceiling and small
   atomic IPC frames on two simplex pipes. Malformed/incomplete audit receipts
   remain unknown. Cancellation arriving during ordinary recovery is deferred
   only until bounded cleanup finishes, then propagated to stop the caller.
   Reconnection discards the old child's IPC entirely.
4. [x] **Bounded installed attribution observation; retain uncertainty.**
   One 20.001-second read-only window, 92 database-wait samples and 19 status
   requests retained 37 distinct in-window work samples: seven over 100 ms and
   zero at/over one second. There were no observation errors; paper processing
   was fresh before/after. Query observations were almost entirely inactive
   clients awaiting commands; one active projection read and one active update
   were sampled without reported waits. Four of the seven estimated slow work
   intervals contained any wait snapshot, and three contained none. This cannot
   exclude unsampled database/transport waits or establish a unique stall cause.
   A subsequent native thread-state read succeeded (19 application threads,
   one running/eighteen waiting); the requested WMI thread-counter read was
   unavailable. No installed financial-thread identity was retained, so these
   host states cannot be assigned to a particular financial interval. New source
   tags the existing timing receipt with `measured_thread_id` for future controlled
   correlation, without changing measurement intervals or guard thresholds.
5. [x] **Installed state and existing authorization remain preserved.**
   Installed process/API still reports `fca588586`, paper-only, fresh processing
   and no reported paper error. Installed inspection used HTTP GETs, authenticated
   read-only metadata queries and native process/thread inspection. No installed
   source, service, account, journal, configuration or model was changed. The
   single approved trained-v2 attempt is unused; no dispatch, paid call, model
   download, holdout exposure, model activation or financial-policy change occurred.
6. [ ] **Separate merge/install/restart and installed repair acceptance.**
   Draft source delivery does not fulfill this boundary. Concurrent trained-model
   operation, active-position protection and the cause of the earlier one-second
   stalls remain unproven; no cache/RAM tuning or permissive threshold is inferred.

## Verification and retained failures

- Actual-owner initial counterexamples: five failed / one passed. They reproduce
  history/storage masking, ancillary suppression of a due audit and expiry's
  stored/computed availability disagreement. Original receipts remain private.
- Final native Windows/disposable PostgreSQL affected-owner selection: **121
  passed**, no skips, one existing TestClient deprecation warning, 181.12 seconds.
  It includes the financial reader, read-only rejection, consistent snapshots
  across a writer commit, real connection failure/restoration before and after a
  good audit, critical supervision, API/notice states, streaming, projections,
  resilience and updater shutdown. The earlier expanded run retained one fixture
  timeout / 108 passes: its six-second wait omitted the actual five-second refresh
  plus three-second connection budget. The fixture now permits ten seconds;
  operating deadlines, freshness and guards are unchanged.
- Initial hosted head `d7725d6`: native **634 passed / 1 failed / 210 skipped**;
  full PostgreSQL **972 passed / 1 failed / 82 skipped**. Both failures were the
  same health fixture, which supplied only a historical balanced flag. The
  corrected fixture uses the real current-status producer and verifies the
  existing health predicate rejects pending/expired/unavailable audits. The
  health gate itself was not relaxed. Ownership and compiled-browser jobs
  passed on that initial head; they do not make the failed jobs green.
- Two later native retries were interrupted and retained. A stack-captured
  malformed-receipt regression identified cancellation being swallowed during
  ordinary error cleanup after the child had exited. Cleanup now propagates
  cancellation after completing its bounded resource closure. Both malformed
  and incomplete-receipt cases pass in isolation and in the final 121-test run.
  The disposable QA cluster also required WAL recovery after an observed prior
  interruption; its log remains private. No operating cluster was restarted.
- Integrated hosted head `c02a0fd`: native **638 passed / 212 skipped**, with
  successful dashboard/ownership/browser checks. The inherited memory job had
  **73 passes / 1 failure**, and full PostgreSQL had **1,048 passes / 3 failures /
  84 skips**. One inherited fixture started at ambient 07:58; its six simulated
  retries crossed the real 08:00 occurrence boundary and legitimately created
  another retrieval receipt. That counterexample is reproduced, retained and
  corrected by placing the fixture clock at noon after its synthetic inputs.
  No operating schedule, time or reviewer behavior changes. The two other
  failures were owned PDF/background child cases in the PostgreSQL CI job,
  which had not installed the application package. The job now uses the same
  declared editable source installation as native memory verification; parent
  pytest path injection alone cannot supply a child's imports. Final hosted
  acceptance must validate this wiring. Locally, all **74 memory/reviewer tests
  pass**, including the deterministic boundary regression.
- All five hosted gates passed on `30d995e` after those harness corrections:
  native **638 passes / 212 skips**, full PostgreSQL **1,051 passes / 84 skips**,
  memory/reviewer **74 passes**, runtime ownership **46 passes**, and the compiled
  seven-state browser check. This remains pre-review evidence. A subsequent
  source review reproduced an incomplete optional sample becoming a generic
  worker failure after a valid audit. Required sample metadata is now validated
  at the IPC boundary; malformed samples are unavailable monitoring, retain the
  actual completed audit and do not become a financial failure. All **nine**
  final native reader/driver/lifecycle cases pass, no skips, 23.45 seconds. The
  new counterexample and original failure are retained. Final independent Codex
  review and exact-head gates are reported in the owning PR, rather than treating
  a previous head's successful jobs as proof of a later correction.
- All five gates also passed on `ecda63d`: native **638 passes / 213 skips**,
  full PostgreSQL **1,052 passes / 84 skips**, memory/reviewer **74 passes**,
  runtime ownership **46 passes**, and compiled Accounts/browser acceptance.
  The independent Codex review of this exact head found one material integration
  issue despite those green gates: the monitoring producer added a seventh key
  without registering it in the notice consumer. Every full batch failed
  validation, rolling back existing notice updates. Two actual-owner
  counterexamples failed before repair, then both passed in **1.91 seconds**.
  The consumer now accepts the explicitly supported key, preserving all size,
  source, confirmation and capacity constraints. Regressions exercise the normal
  refused-research supervisor plus full producer -> registry -> API transitions,
  prior-audit preservation, a critical alert, confirmed recovery, existing alert
  updates and side-effect-free reads. The review found no further material issue;
  it inspected source and an isolated rejection, without rerunning native/browser
  suites or inspecting the installation. The affected notice/contention/health
  owner selection passes **35 tests**, one existing warning, **59.21 seconds**;
  its one real-role PostgreSQL case was explicitly deselected while the disposable
  cluster was stopped and remains covered by the full hosted PostgreSQL gate.
  Ruff and strict Windows-targeted mypy pass (**108 source files**).
  Final repair review and exact-head gates
  remain separately reported in PR #63; pre-repair green jobs do not cover it.
- Independent review of the repaired `dcd7e6d` delta confirms the finding resolved,
  with no further material issue. Its in-memory SQLite comparison uses actual
  notice-owner transaction/event methods: the old batch persists nothing, the
  corrected batch commits all seven keys, and unsupported keys still fail without
  losing earlier committed rows. Review scope does not include native/browser
  suites, hosted gates or installed inspection.
  On this head, PostgreSQL **1,054 passed / 84 skipped**, memory/reviewer **74
  passed**, ownership **46 passed** and the compiled browser gate all succeeded.
  Windows tests **640 passed / 213 skipped** in **369.45 seconds** and the dashboard
  TypeScript/build (**1,932 modules**) succeeded, but the combined native job
  exceeded its eight-minute complete-job budget during final cleanup and is
  **cancelled**, not green. Retain that failed acceptance receipt. The unchanged
  dashboard install/build now runs in its own eight-minute Windows job; every
  native test and the original native time limit remain. Final acceptance requires
  all **six** separate gates on the final exact head, as recorded in PR #63.
- Native driver cases cancel an actual disposable `pg_sleep(30)` session and
  drain after one/two cancellation requests, preserving writer/history and
  subsequent writer usability. A client-side block has **no test release**; fixed
  drain/termination finishes it and its owned database session disappears. The
  operation-timeout case injects a two-second **test-only** sample budget; drainage
  uses the actual four-second source budget. Incomplete audits publish no result.
  Oversized optional history cannot hide the audit delivered beforehand.
- Pinned native and installed driver introspection: psycopg **3.3.4**, binary
  libpq **18.3**, bounded-cancellation support available. Disposable native
  PostgreSQL is **17.2**. A separate `pythonw` native probe confirms a non-visible
  child console, an actual balanced read and clean owned-child drainage. This
  demonstrates the windowless parent path, not installation of this successor.
- Before incorporating #61, Ruff and strict Windows-targeted mypy passed
  (**102 source files**); dashboard TypeScript/production build passed
  (**1,930 modules**). After integration, the actual API/reader/health native
  selection passes **34 tests**, no skips, one existing warning, 73.82 seconds;
  Ruff and Windows mypy pass **108 source files**, and dashboard build passes
  **1,932 modules**. The final source operation budget starts before child startup
  and request dispatch; exact-head hosted gates include that final adjustment.
- Actual compiled browser + disposable API/PG: seven sequential states,
  pending → balanced → failed → balanced → expired → balanced → imbalanced,
  API/health agreement, retained audit dates/revisions, distinct status colors,
  390-pixel viewport and zero browser exceptions. API responses are not mocked.
  Initial browser failure exposed the pending label; a subsequent harness
  failure toggled an already-open details element. Both failed logs remain
  private, and the final complete rerun passes. Fixture times/failure/expiry and
  presentation liveness are synthetic; positive/negative audits use the actual
  disposable journal. These are software/UI proofs, not market or trading proof.
- The added `browser-monitoring` CI job repeats this compiled workflow using
  disposable password-authenticated PostgreSQL and Playwright **1.62.1**. Its
  uploaded receipts/screenshots contain synthetic fixtures only. Existing native,
  runtime-ownership, full PostgreSQL and #61's persistent-research gates remain
  separate; exact-head hosted
  results are reported in the owning PR after completion, with skips retained.

### Observer overhead and limits

The 20-second observer used 0.391 seconds of its measured Python thread's CPU.
Database probes: median/p95/max **2.686/3.899/11.546 ms**. Status requests:
**53.098/142.305/283.014 ms**, including response transport/decoding. The later
native process-thread read cost **55.368 ms**. Provider/financial workload,
other workstation activity and observer effects were uncontrolled; this is not
a matched optimization experiment. Seven sampled slow intervals span roughly
103–149 ms and 46.875–109.375 ms of charged financial-thread CPU. They are not the
earlier severe low-thread-CPU intervals in #62. No model was dispatched.

Next controlled attribution should use the existing phase receipts and the
tagged native thread ID, align owned DB wait/host-state observations to complete
work intervals, retain observer cost and missed samples, and keep the full guard.
Unique cause and an optimization choice remain open when those observations do
not identify them. No further long wait for admission or speculative cache change
is part of this source follow-up.

## Reproduce the isolated UI check

Use the pinned Python requirements, built `apps/web/dist`, a separately owned
disposable PostgreSQL config and a fresh QA directory. Set a private arbitrary
`QTRADES_BROWSER_QA_TOKEN`, then run
`tests/browser/financial_monitoring_server.py --directory <fresh-qa-directory>
--database-config <disposable-config> --web-dist <built-dashboard>` on loopback.
Set `QTRADES_BROWSER_QA_OUTPUT` and make Playwright 1.62.1 available through
`NODE_PATH`; run `node tests/browser/financial_monitoring.cjs`. The harness requests
clean shutdown and the server drops only its generated disposable schema. Never
point this fixture helper at operating data. Original private installed evidence,
configs, query/host receipts and native failure logs are not committed/uploaded.

The cancellation choices follow [Psycopg's cancellation contract](https://www.psycopg.org/psycopg3/docs/api/connections.html#psycopg.Connection.cancel_safe):
request success does not imply completion, and bounded native cancellation needs
libpq 17+. [PostgreSQL statement timeout](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-STATEMENT-TIMEOUT)
is per server statement. The owned-child fallback therefore covers the remaining
client/drain lifecycle. [Python's spawn/termination contracts](https://docs.python.org/3.12/library/multiprocessing.html)
also require that terminated-child IPC is discarded. Browser CI uses the
[documented Playwright installation path](https://playwright.dev/docs/ci).

## R63-1: preserve known optional-refresh failures through retry audits

### Original reproduction and correction

At published `932c2b729d291114ff105a5cc0cd36462743eb44`, the actual native Windows
runtime/reader and disposable PostgreSQL selection recorded **4 failed / 1
passed / 11 deselected**, 71.20 seconds. History-only, storage-only and both
independent-recovery directions falsely became balanced after a new successful
audit arrived while a previously failing optional query remained held. The
healthy routine in-flight control passed. These native receipts preceded complete
Python lock restoration; their recorded environment is not retroactively changed.

The original-source compiled Accounts run reproduced the same defect after
restoring all 33 Python lock versions. Its saved final held probe established a
live owned reader, no whole-operation error and unchanged completed-sample time.
Owner, API, health and Accounts falsely reported current balanced monitoring;
the actual research prerequisite opened. This run failed its acceptance assertion
and closed the owned server normally in 25.843 seconds.

These fixtures use the actual `FinancialReadback`, spawned `ReadbackWorker`,
runtime loop, API and compiled UI with real disposable financial history. Optional
query failures/holds, presentation liveness and a 61-second audit-scheduling
advance are explicitly synthetic. No production method is copied into a probe,
no passing audit is fabricated, and no model or operating database is used.
The earlier copied-method Linux probe remains a separate synthetic finding.

The correction changes only production `src/trading/tiered_runtime.py`:

- `_accept_financial_audit` publishes the completed audit without clearing an
  unresolved whole-operation or optional-query error. Confirmed negative audits
  still wake financial supervision immediately, before ancillary queries.
- `_accept_financial_sample` retains named failures in the existing sample receipt
  until that query supplies a successful result. Recovery of one query cannot
  clear another query's failure or a query omitted from the sample. A completed
  whole sample clears its operation error.
- `journal_status` derives availability from those existing owners. Performance,
  API, health, notices and the research prerequisite share that result. Healthy
  routine refreshes remain available while a valid audit has no known failure.

`latest_query` timing still describes the last completed sample; its
`refresh_errors` now retains unresolved named errors until genuine recovery.
There is no additional store, scheduler, general state machine or status authority.
Financial-loop work, writer ownership, audit validity, guards and the existing
15-second operation / four-second drain / one-second termination limits are
unchanged. Optional failures remain nonfatal to financial supervision.

### Corrected source and independent review

Source/test commit **`5c8eca9ab128dfbc242f8ea87d2c3aaac89b2443`**, production blob
`93c8c6c73d1c0643905bebe9dc0c400254fcb6c8`, contains the reviewed correction and
regressions. Subsequent publication documentation does not change those files.

| Local evidence | Observed result and scope |
| --- | --- |
| Initial seven recovery cases | 7 passed / 9 deselected, 121.12s; original pre-lock-restoration environment and earlier timeout fixture retained |
| Stronger forced recovery | 1 passed, 39.39s; waits for actual owned-child termination before releasing the hold, then proves fresh-reader recovery |
| Broader native/disposable PG selection | 125 passed, no skips, one existing warning, 296.43s; eleven affected files, all seven new transition cases and existing negative/incomplete audit, notice, API, reader cancellation and identity-safe shutdown coverage |
| Final outage-fixture delta | 2 passed / 13 deselected, 28.39s; adds initial balanced/available/empty-errors assertions before real bad-endpoint injection, retains 10s outage and 8s recovery limits |
| Compiled ordinary Accounts/API/PG | 23 actual-owner checkpoints plus seven original presentation states, 141.563s, browser/server exit 0, 390px viewport, zero browser exceptions |
| Static checks/build | Ruff 0.16.9 `src tests`; strict Windows-targeted mypy 2.3.1, 108 source files; dashboard TypeScript/build, 1,932 modules |

The broader run preceded only the final three healthy-start assertions, whose
two affected cases were then rerun. Selections overlap and are not added together.
The compiled checks cover each independent failure, newer audit during a held
retry, repeated failure, partial recovery, healthy routine refresh, real timeout
and termination, restart and genuine recovery. Together with native owner coverage,
they verify nonempty history, audit date/revision, immediate imbalance propagation
and incomplete-audit refusal.
The complete notice producer batch passes the registry and API through confirmation
and recovery. The real lab prerequisite is checked without model dispatch or new
experiments.

The task-owned Python 3.12.10 environment matches all **33** requirements-lock
versions. The local browser uses existing offline **Playwright 1.63.0 / Chromium
151.0.7922.34**, explicitly different from unchanged CI's **1.62.1** pin. Receipt
filenames containing `pinned` refer to the restored Python lock; they do not prove
browser-version equivalence. The hosted browser gate is separate qualification.

Independent Codex review found no remaining material actionable findings in the
correction and affected contracts. Its two fixture findings were repaired: a
post-screenshot final probe proves the held interval still exists, and the real
connection-outage fixture proves healthy monitoring before injection. Review
inspected source and retained receipts, not a new test run or installed state.

### Retained failed attempts and remaining limits

- The constrained native attempt had five fixture setup/cleanup access-denial
  errors; these are not behavioral reproductions. The initial dashboard attempt
  failed with `spawn EPERM`; the later native build is a separate pass.
- The first corrected browser attempt reached timeout completion but stalled on
  QA control recovery and hit its 300-second runner limit. A native isolated probe
  reproduced a shared `Event.set` stall after terminating its waiting child.
  Test controls now use single-writer RawValue flags with bounded polling; browser
  closure is guaranteed even when the owned-server shutdown request fails.
  Production IPC and deadlines were not changed.
- A diagnostic-wrapper browser attempt failed when its owned server exited with
  access violation **3221225477**. The cause remains unverified; no application,
  driver or wrapper cause is asserted. The ordinary direct browser pass does not
  relabel this failed attempt.
- The first broader native selection remains **1 failed / 124 passed**, one
  warning, 295.19s: the after-good-audit connection-outage case exceeded its 10s
  observation limit. A separate unchanged-predicate diagnostic rerun passed both
  cases in 27.22s and did not establish that failure's cause. The fixture now
  observes the public derived monitoring error, retains timeout diagnostics,
  checks the initial healthy state and uses the same deadlines. The subsequent
  125-pass run and final two-case pass are separate receipts, not a reclassification.

All earlier C60 failures, interrupted/cancelled jobs, skips, historical installed
observations and reviews retain their original revision and limitations. All six
unchanged gates must pass on the final published head: native, windows-dashboard,
runtime-ownership, postgres-integration, browser-monitoring and persistent-research.
Results and skipped counts are reported in the owning PR rather than inferred
from an earlier head. No local competing full suite was launched while another
project's full suite was active; local heavy verification ran serially.

Private QA logs, hashes, screenshots and environment receipts remain under the
task-owned `outputs/qtrades-monitoring-repairs/r63-1-20261005-01` directory, outside
Git. The owned disposable cluster and servers were stopped after local verification;
the open PR worktree and other lanes remain available. Safety stashes are preserved.
A bounded loopback health GET at **19:09 UTC** observed installed
`fca588586f9b72e9506caef6384ee8e65edea738`, running paper, fresh, balanced and no
reported paper error. No operating SQL, installation, restart or service/task change
was part of this recovery follow-up.

This is source/isolated-QA acceptance only. No model call, paid call, training,
download, holdout consumption, capture campaign, financial/storage-policy change,
merge or trading activation occurred. The separately approved trained-v2 attempt
was not consumed. Installed successor acceptance, actual model/market qualification
and broader research completion remain separate. Preserve #61's owner, #57/#62's
historical receipts, #64's compression study and the private Training Lab.
