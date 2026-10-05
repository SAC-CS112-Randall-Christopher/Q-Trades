# Financial monitoring correctness follow-up — October 5, 2026

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
