# Paper/model coexistence optimization — October 5, 2026 UTC

Continuation of #28/#48 from main/installed `fa3accde7667404a7751f75a8d1b1cc6978a7808`.
Chris requested implementation and testing to let the trained model run alongside
paper processing. Previous #54–56 rollout is complete; #57 remains a separate
documentation draft. This repair is source/isolated QA, not another installation.

## Concrete changes

1. Financial reconciliation, storage counts and recent primary-history queries
   leave the synchronous financial loop. A single sequential worker uses a
   separate authenticated PostgreSQL connection. Its default mode and each
   repeatable-read transaction are read-only. It retains the original password,
   schema/options, query timeouts, complete reconciliation, archived-account
   checks and exact storage counts. It does not acquire writer ownership.
2. Recent history refreshes every five seconds; reconciliation/storage refresh
   every sixty seconds. Errors retry through the normal supervisor without
   restarting. An unavailable or 120-second-old audit closes optional research;
   an actual imbalance closes it immediately and stops the financial supervisor.
   Status identifies original observation time, checked revision, availability,
   sanitized failure and query durations. Shutdown drains the owned query before
   closing its connection, including a repeated cancellation.
3. Old slow samples cannot renew a five-minute cooldown on a newly fast pass.
   A new slow pass in a four-of-twenty window still renews it; any one-second stall
   still renews it. The 100-ms, four/twenty, 1,000-ms and 300-second limits remain.
   Complete critical-loop work, including post-commit evidence capture, remains
   measured. Background query durations and age are disclosed separately.
4. The direct trained-v2 runner selects one allowed logical processor from each
   of two distinct physical cores. It previously selected the first two allowed
   processors, which are siblings on this host. The existing two-thread/two-
   logical-processor ceiling, Windows IDLE priority, CPU float32, 24-GiB memory
   ceiling, eight-GiB reserve, 600-second budget and exact model identity remain.
   Ordinary numerical workers keep their existing selection. Unsupported or
   insufficient topology fails closed. Actual affinity and selection policy are
   retained in the serving response. This does not reserve those cores against
   other applications or prove trained-model throughput.

No financial-engine, balance, parent, account/slot, fill, funding, economic,
delayed-outcome, journal/history or G: retention policy is changed. The RAM
projection cache remains SQL-verified and commit-authoritative. The numerical
CPU probe below uses no model, weights, protected evaluations or GPU.

PostgreSQL documents that repeatable-read queries observe one transaction
snapshot: [transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html).
Windows supplies actual physical-core relationships:
[processor topology](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getlogicalprocessorinformationex).

## Measured evidence and its limits

The declaration precedes the measurement. All raw data, account values, DSNs,
workstation details, paths, process IDs and original failed receipts remain
private. Public aggregates do not substitute for an installed changed workload.

### Actual retained-history, read-only comparison

One warmed authenticated read-only connection, four synchronous/worker/worker/
synchronous blocks, six complete audit samples per block, 10-ms test heartbeat,
45-second maximum. All twelve audits per method are balanced; no operating
writes. This ran against the actual retained database, not a small history fixture.

| Metric | Synchronous read | Worker read |
| --- | ---: | ---: |
| Queries | 12 | 12 |
| Query median ms | 164.691 | 157.537 |
| Test-loop heartbeat samples | 22 | 130 |
| Heartbeat p95 delay ms | 161.454 | 15.358 |
| Heartbeat maximum delay ms | 182.851 | 19.166 |

Total observation: 4.485 seconds. Queries are still substantial; their move
allows the event loop to progress while they run. Different heartbeat sample
counts follow from that progress. This does not measure the changed installed
financial loop, prove lower financial-transaction latency, establish active-
position protection or demonstrate simultaneous trained-model inference.

### Native processor-placement probe

Four old/distinct/distinct/old children, two native hashing threads, two seconds
per child, one-MiB payload per thread, Windows IDLE priority and exactly two
allowed logical processors. Actual topology shows one/two/two/one physical
cores respectively. Mean throughput: old 482.745 hashes/second; distinct 627.444
hashes/second, about 30% higher in this bounded numerical workload. This is not
model response speed, qualification or protection against all host contention.

### Storage discovery and preservation

A fresh installed check reports local capture disk reserve and raw recording
failure in addition to engine cooldown. C: is below the unchanged five-GiB
reserve. Paper reports fresh/error-free processing and no active positions;
the recording gap remains a real failure. There is no inference attempt.

Completed task-owned QA output and two confirmed-stopped QA clusters were
preserved on G: with complete SHA-256/count verification and original paths
maintained by directory junctions. The first move stopped at read-only test
fixtures; both sides were reconciled to the original 4,977 files before verified
copy/cleanup. Nothing was discarded. Existing dependency links to another
worktree were left alone. Source, operating account data/configuration, live
services, unrelated owners and model/holdout artifacts were not altered.
The reclaimed task storage is insufficient to establish the required local
reserve. Do not relabel this as capture recovery or reduce the reserve to claim
model admission. New QA temporary output is on separately owned G: storage.

The later finite software run uses a private fixture-placement helper: ordinary
paper-admission fixtures physically reside on G:, while recovery timing and
remaining software fixtures use a bounded local folder. It supplies no fake
resource readings and changes no test, assertion, deadline, clock or policy.
The existing interrupted-capture test exceeds its five-second deadline on the
slower G: storage and passes on fast local storage. The ordinary low-information
paper comparison refuses C: admission under its real reserve and passes with its
files on G:. Both cases pass together with the declared placement.

The original all-G: and all-C: runs were interrupted; their failed/partial logs
and fixtures remain distinct evidence. The local fixture copy (4,418 files) and
the completed release-source dependency copy (5,255 files) were subsequently
hash-verified on G: with their original paths available. During the split run,
local free space fell below its initial two-GiB QA headroom declaration. That
deviation is retained, not accepted as an operating resource profile. Software
assertions cannot establish host capacity or concurrent trained-model execution.
During that split run the separately owned QA PostgreSQL cluster measured
approximately 90 MiB, including 64 MiB of WAL. It was subsequently stopped as
recorded below. No operating database setting was changed.

The first completed split-storage suite recorded 1,031 passes and ten failures
in 2,631.10 seconds. All ten storage-expansion fixtures had still landed on C:
and failed during initial evidence admission with the actual free-space reserve.
The unchanged file passes on G: (ten passed / one Windows symlink-permission
skip). That focused result does not make the failed full run green. The corrected
fixture placement includes this file. The complete workstation rerun could not
finish: local free space abruptly fell to 123 MiB, below its declared one-GiB
floor, and it was stopped. Its buffered log reaches 69%; there is no completed
result or JUnit report. This remains partial evidence, not a passing native suite.

Before the rerun, the completed failed fixtures (4,281 files / 0.129 GiB) and
three completed type-check caches were also hash-preserved with their original
paths available. Its separate finite-QA declaration bounds remaining local
fixtures to 300 MiB with a one-GiB minimum local QA reserve. The observed previous
local total was 129 MiB. These software-only bounds neither change nor satisfy
the five-GiB operating reserve. The remaining task-owned local directories total
only a few hundred MiB; shared temporary folders with other or unestablished
owners remain unchanged.

The interrupted rerun's local fixtures (919 files / 117,728,622 bytes) and the
confirmed-stopped isolated database (999 files / 94,782,543 bytes) were then
fully hash-preserved on G:, with original paths available. No test Python process
remained. Only that owned QA cluster was stopped. C: still has only a few hundred
MiB free; the cause of the abrupt loss remains unattributed. Neither the fixture
sizes nor the unchanged six-GiB page-file allocation account for that loss.

A subsequent installed observation still has fresh/error-free paper processing,
about 50.5 GiB of available RAM, engine cooldown and the local recording failure.
Recording omissions remain visible. The RAM allowance is not the present
admission blocker; the changed financial loop itself is still uninstalled.

A later fresh installed sample records 210.116 ms of complete work: reconciliation
45.314 ms, storage counts 84.307 ms and recent history 9.249 ms, about 139 ms
together; the financial calculation is 0.709 ms. Available RAM is then about
59.7 GiB, while local disk is about 1.9 GiB and recording remains paused. This
locates the monitoring contribution in that sample; subtracting it is not a
measurement of the changed installation or concurrent model execution.

Read-only Windows memory counters separately report 95.691 GiB physical RAM,
58.828 GiB available and 50.961 GiB committed against a 101.691-GiB commit limit.
The system-managed C: page file reserves six GiB; current/peak use is 32/808 MiB.
These idle-host observations identify headroom, not the trained model's peak.
No memory or page-file setting was changed. A different Windows storage policy
is a separate decision: sizing depends on peak commit and crash-dump needs,
not a single low-usage observation ([Microsoft page-file guidance](https://learn.microsoft.com/en-GB/troubleshoot/windows-client/performance/how-to-determine-the-appropriate-page-file-size-for-64-bit-versions-of-windows)).

Additional bounded read-only metadata shows an approximately 835-MiB operating
database, a one-row approximately 30-MiB projection relation, regular autovacuum
and no pinned reader transactions in that database. This does not support a
stale-reader bloat diagnosis. The server's WAL files were not accessible through
the Windows filesystem path. The active Docker data disk on C: is about 141 GiB;
it is a substantial space holder, not a confirmed cause of the abrupt growth.
Operating files, Docker storage and services remain untouched. Moving database
storage to the slower G: drive would need its own measured placement decision.

## Verification ledger

- Affected reader/driver/projection/stream/counter/regression set: 77 passed
  with real isolated PostgreSQL. Subsequent focused topology/loader/guard
  testing corrected fixture expectations and preserved the original failures.
- Reader regressions cover a concurrent ordinary financial commit, one coherent
  database snapshot, actual read-only rejection, outage/restoration through the
  continuing background loop, confirmed-imbalance handling through the normal
  supervisor, audit expiry, and query drain on shutdown.
- Actual Windows child verifies two physical cores, two logical processors and
  IDLE priority. Pure topology cases reject incomplete, foreign-group, overlapping
  and insufficient allocations. Loader call-contract fixtures remain synthetic.
- Ruff and strict Windows-targeted mypy pass; 101 source files checked.
- The new fast-recovery regression fails against unchanged main: a fast pass
  extends the deadline from 1300 to 1301. It passes with this repair.
- Final focused reader/topology/guard/disk set: 15 passed. The placement control
  above adds two passing unchanged tests on their actual declared volumes.
- Exact source-head hosted run 37266632682 at `49137cd4761e1fdea5011c20aeeb60baee698ba4`
  passes both jobs: native 635 passed / 196 skipped (no hosted PostgreSQL),
  runtime ownership 46 passed. The TypeScript/Vite build passes with 1,930 modules.
- The completed workstation full run remains failed (1,031 passed / ten failed);
  the corrected rerun remains interrupted. The private manifest binds 296
  application, script, test, dependency, dashboard and CI files and the fixture
  helper's SHA-256. All 295 files other than the subsequently extended workflow
  retain their original content. Documentation changes do not replace that
  source-head evidence.
- To complete broad source integration without adding local disk pressure,
  `22f12e985dae029d7fbe6257ecfd86255e0b1004` adds a standard Ubuntu job with
  disposable password-authenticated PostgreSQL. Both existing Windows job
  bodies, every selector and their eight-minute budgets remain unchanged.
  No operating data, private models or larger/paid runners are used.
- [Hosted run 37278413162](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/37278413162)
  passes all three jobs at that head: complete portable PostgreSQL suite
  959 passed / 82 skipped / one warning in 169.15 seconds, PostgreSQL 17.11;
  Windows selected suite 635 passed / 196 skipped (no configured PostgreSQL);
  runtime ownership 46 passed in 19.54 seconds. The dashboard build passes with
  1,930 modules.
  The portable result does not make the failed/partial workstation runs green
  or establish actual Windows model coexecution. The public repository uses
  free standard runners ([GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)).
  Both new test files remain selected by the Windows native job.

## Remaining acceptance

Keep the PR draft and unmerged pending the applicable release authorization.
Resolve the actual local recording reserve without touching unrelated private
data or waiving capture protections. Restore safe workstation QA capacity before
claiming a complete local native acceptance. Use the existing updater for any approved
installation, preserve the financial prefix/configuration/parents and verify
normal activity/history/Journal, recording and guard recovery in the running app.

Then reuse the already retained normal development question and its existing
single unused authorization. Record the actual trained-v2 original response,
full operating guard, model identity, resources and before/during/after paper
health. No automatic answer retry or base/GGUF substitution. This source repair
does not complete that model trace, role qualification, real mature paper
feedback/continuation or CP23 sustained/usefulness acceptance.
