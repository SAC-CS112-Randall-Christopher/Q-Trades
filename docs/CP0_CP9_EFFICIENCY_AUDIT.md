# CP0–CP9 audit — source implementation and measured finite proof

All remaining checkpoint implementations are reviewable drafts. This audit reads
the full stack, preserves prior red/green receipts and implements the measured
history costs and concrete integrity/UX findings. Original runtime/trial, native
updater, advisory model/GIS settings and private data are unchanged. Merge,
installation, elapsed prospective evidence and live feasibility are separate.

| Checkpoint | Scope inspected and conclusion | Change or retained limit |
|---|---|---|
| CP0 | Manual updater copy/build/backup/stop/restart and native fixtures | Preserve simple workflow and code-only copy boundaries; no installer redesign. First approved workstation update remains unproved. |
| CP1 | Valuation at fill, buy cancellation, latched stops, recovery, transaction rollback | Keep deterministic cash/risk authority and one writer; no optimization bypasses marks, losses or invariants. |
| CP2 | Whole-account equity/flow/costs, benchmarks, unknown marks, operating allocation | Existing bounded shared report computation retained; historical scenarios not rewritten. Future actual broker fees remain unknown. |
| CP3 | Shared causal feed, separate accounts, launch/control identity, failure isolation and paged journals | UI waits for the accepted control version before another account action; no relaxation of stale-request fences. |
| CP4 | Frozen inputs/plans, information consumption, queue/leases and receipt reads | Project a small immutable manifest; skip input decoding and launcher-side snapshot loading. Serial, abortable UI polls stop after terminal receipt follow-up. |
| CP5 | Three registered mechanisms, fitting/availability, artifact admission and deterministic exits | Validate fixed timing, cost, horizon and risk fields even with a recomputed hash. Invalid artifacts block new signals while fresh executable data permits a recorded risk-reducing exit. |
| CP6 | Finite campaigns, coverage, budgets, restart, total-account cap and worker pressure | Retain 2/4/8 iterations, queue eight, one child, at most two IDLE processors/256 MiB/25 seconds. CP8 repaired actual-worker PID supervision. No advisory-runtime/GIS change. |
| CP7 | Protected whole-account comparison, drift, report persistence, role approval and rollback | Keep full hashed reports in the immutable financial journal; hot state/UI hold compact references. Exports and approval verify the full receipt, including legacy migration and restart. |
| CP8 | Local/hosted proof, fixed capacity/soak, writer/crash/backup/resource faults and authentication | Repeat 1/10/20 idle/busy and five-minute soak with exact committed driver/source hashes, real child identity and actual account/economics status serialization. |
| CP9 | Dated venue/public metadata, total-capital economics, unresolved account/funding/adapter work | Read-only no-go packet; one initial request and explicit refresh, no recurring private lookup or enabling action. Improve cost-table readability. |

## Before/after contract and evidence

`scripts/verify_efficiency.py` declares thirty research receipt reads using a
7,033,881-byte synthetic frozen input and twenty accounts with thirty-two retained
reports, each with 512 discarded windows. Twenty-four no-op financial transactions
isolate projection decode/write cost. This is a deliberately large bounded history
case, not normal market latency, returns or a substitute for the actual engine soak.
The same driver hash was used against detached CP9 baseline 0cfd601 and audited
implementation hashes; platform, clocks and complete observations are retained.

Initial discovery: receipt get p95 61.23 ms; state 2,895,274 bytes; write p95
224.44 ms. Repeated matched-driver baseline: get p95 62.64 ms, peak single-read
Python allocation 19,188,635 bytes; state 2,895,292 bytes; write p95 257.79 ms.
Initial audited repeat: get p95 7.77 ms, allocation 5,471 bytes; state 39,836 bytes;
write p95 3.80 ms. Full journal reconciliation balanced in every measurement.
All runs remain retained; timing varies with the host and is not a universal speedup.
Final clean-source receipts and capacity/soak results are in the review folder.

The registry manifest is an immutable projection of the original snapshot. Legacy
inputs and hashes remain byte-identical; full worker inputs remain available.
Financial report compaction verifies old journal receipts before replacing their
duplicate projection. No report, rejected window, event or journal line is pruned.
The unique report lookup index avoids scanning growing financial history. An
eligible paper designation cannot trust only a displayed summary or forged receipt.

## Verification and failures

Final local full PostgreSQL suite: **381 passed, no skips**, 83.66 seconds
(earlier audit full run: 76.74 seconds).
The affected registry/numerical/forward/audit component run had **38 passes**;
lint, 47-module types and production dashboard build passed. The final independent
report-reader/forward component check had eighteen passes. Manual exports use a
separate read-only connection, keeping them outside the writer's transaction.
Added regression
contracts cover legacy manifests, complete receipt preservation/restart, hashed
approval, modified numerical risk/cost/timing and safe risk reduction. Original
CP0–CP9 software and fault coverage remains included in the full suite.

The first audit browser check exposed a new empty-campaign null guard in the
waiting-control UI: the initial dashboard rendered, then disappeared when paper
status arrived. The guard now explicitly requires a pending control before
reading its version; fresh empty-campaign navigation and subsequent workflow are
rechecked. This failure is retained, not called a successful original browser run.
Formatting failures were repaired; they do not alter the original reported full
suite. Prior CP4 clean-checkout import failure, CP5 real-history gaps and CP8
launcher/supervised PID mismatch remain in their checkpoint receipts.

## Remaining efficiency work, ordered by evidence needed

1. Measure actual authorized workstation feed-to-decision-to-paint latency and
   sustained observation/position-management behavior after approved installation.
   Current synthetic metrics exclude network/paint and whole-host ArcGIS latency.
2. Track history growth during real forward use. Market retention can be bounded;
   financial/research history must remain durable. The 512-window comparison bound
   returns an explicit truncated/no-promotion result; extending it needs exact
   membership and a reviewed continuation design, not silent first-N evidence.
3. Benchmark journal insert batching only if actual fill-heavy transactions remain
   dominant. Current serial inserts retain exact event/line order and transaction
   guarantees; no correctness-sensitive rewrite was justified by the finite SLOs.
4. Measure research pressure alongside actual permitted advisory/GIS workloads
   before considering more processors or parallel fit children. The existing
   protected pressure gate and fixed trusted child bounds remain conservative.
5. Obtain subsequent matched forward evidence before judging research usefulness.
   Fast fitting, synthetic after-cost labels and a successful soak cannot establish
   repeatable advantage. CP9's account/finality/permissions and live-adapter work
   remain blockers to any separate live decision.
