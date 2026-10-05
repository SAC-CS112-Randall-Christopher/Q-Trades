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
- Full native and exact-head hosted results will be appended after completion.
  All existing hosted selectors and the separate ownership job remain; both new
  test files are selected by the native job.

## Remaining acceptance

Keep the PR draft and unmerged pending the applicable release authorization.
Resolve the actual local recording reserve without touching unrelated private
data or waiving capture protections. Use the existing updater for any approved
installation, preserve the financial prefix/configuration/parents and verify
normal activity/history/Journal, recording and guard recovery in the running app.

Then reuse the already retained normal development question and its existing
single unused authorization. Record the actual trained-v2 original response,
full operating guard, model identity, resources and before/during/after paper
health. No automatic answer retry or base/GGUF substitution. This source repair
does not complete that model trace, role qualification, real mature paper
feedback/continuation or CP23 sustained/usefulness acceptance.
