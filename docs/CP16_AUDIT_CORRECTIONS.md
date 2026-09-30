# CP10–CP16 integrated audit corrections

This corrects the six findings recorded in issue #1 against main
`852171f3329b8af8e902e8759bc5df092bf0dd17`. The earlier statement that the
research procedures were delivered did not establish an account-comparison
handoff or a trading advantage. Retain that distinction and all earlier receipts.

## Corrected contracts

1. **Availability and expiry.** Calibration, protected memory evaluation,
   contextual/flow delay comparisons and learning use required input/result
   availability rather than market cutoff. An expired result provides no signal.
   The new account counterfactual waits for stored input plus measured inference
   latency and a permitted observation before acting. This is historical research,
   not a claim that today's computation was observed operating in the past.
2. **Exact evidence.** Memory neighbors retain archive type, stable episode and
   expected hash. Compact links read the compact archive in a read-only transaction.
   Full links verify their own archive identity/hash. Integer collisions cannot
   substitute another archive's record. Legacy fitted receipts without typed
   references disclose that exact reopening is unavailable rather than guessing.
3. **A/B/C accounts.** The existing memory-entry plan can declare
   `account_comparison=true`. The existing numerical/contextual memories are fitted
   chronologically, then fresh matched A/B/C accounts run every selected observation
   through the existing engine. Every original source state/event must reconcile.
   There is no first-32 replay prefix, counterfactual state reset, invented fill,
   gap interpolation or forced liquidation. Cash, reserves, open holdings, executable
   final equity, fees, turnover, exposure and drawdown remain visible. Missing source
   continuity, source version, boundary marks or valuation returns an incomplete run.
4. **Costs and controls.** The operator freezes common daily allocation, B/C daily
   additions and CPU-hour rate. Daily allocations cover declared collection/storage/
   routine host costs; measured arm fitting and inference CPU are priced separately
   and charged once. Blank costs remain unavailable. Zero is a declared scenario,
   not evidence of a free host. Entry fees and executable liquidation fees already
   embedded in account equity are never deducted again. One independently funded
   passive BTC benchmark starts once and holds through the entire declared interval.
   It uses the same fees, precision, book walking, later-book rule and expiry. It is
   explicitly distinct from CP7's repeated four-hour reset exposure comparison.
5. **Bounded acquisition.** Flow/exit/size/observation runs select the requested
   interval and ten-second/45-minute causal margins before applying eight MiB.
   Account runs select the complete declared interval and use separately verified
   compact training labels. No unrelated older decision payload is materialized.
   Selection indexes and retained byte metadata avoid scanning payloads to price
   the budget. Genuine oversize, missing dependencies and stopped capture remain
   unavailable; the original full and compact archive limits remain in force.
6. **Separated support and honest summaries.** Incremental admission, neighbor
   selection and scoring require distinct concentration groups and nonoverlapping
   closed intervals. Overlapping observations remain retained. Learning summaries
   measure paired actions against frozen memory. Exit summaries report different
   sell events; sizing reports changed order quantities. Unmeasurable entry counts
   are not applicable rather than literal zero.

## Exploratory handoff and operator interface

Historical matches exposes the account plan and its cost assumptions. A complete
observed priced account scenario can support explicit exploratory paper admission,
including an unfavorable outcome. Synthetic, incomplete, unfitted or unpriced
results cannot. Admission uses the existing single financial writer and idempotent
funding contract, then creates its existing CP7 matched control. Retry preserves
the same artifact, capital and operating assumptions, including a partially
completed candidate/control pair.

The prospective form selects that admitted memory arm, its exact historical
receipt and matched control. The review freezes the existing 28-day window and
configuration without funding another account. Ordinary component combination
still requires independent qualification; exploratory review permits exactly one
linked memory arm. Existing receipts are not rewritten. Original accounts, failed
searches, consumed windows, resource caps, risk limits and human role approval
remain intact. No provider transport, new model family or live order path was added.

## Verification and limits

Regressions reproduce late inputs/calibration, compact/raw ID collision through
the API, overlapping support, oversized unrelated history, genuine oversize and
misleading zero summaries. Account fixtures cover all 40 observations beyond the
short replay limit, open positions, cash, adverse operating costs, unpriced costs,
source corruption/omissions, actual availability, worker dispatch and exact
candidate/control/receipt selection. These are declared synthetic software tests.

The final Windows/PostgreSQL suite passed **478 tests, no skips, 107.56 seconds**,
after the fitting-cost, stored-availability and serialization corrections.
Ruff, Windows-target mypy
(63 source files) and the TypeScript/Vite build passed. Browser verification used
the normal form against a disposable local database and reopened its honest
insufficient-data receipt. No private workstation strategy or account was funded
by this verification.

The bounded native memory child completed in 0.843 seconds, 34.14 MiB RSS, with
two processors and no paid calls. Repeated inference p95 was 0.640 ms; repetition
adds no market support. Two native six-case load runs retained a 20-account idle
failure (108.679/108.109 ms loop p95 against the unchanged 100 ms limit), although
the other five cases passed. Evidence completion now hashes the JSON-compatible
committed state directly and reuses encoded archive bytes; exact source/event
hash verification remains required. Final performance and hosted/installation
gates must be observed before release, not inferred from unit tests.

After this serialization repair, all six native cases passed the original limits.
Twenty-account loop p95 was **91.607 ms idle / 97.112 ms with research busy**.
Both earlier red receipts remain retained. The suite and benchmarks used separate
disposable schemas; the initial stopped-test-service attempt was interrupted and
retained as an environment failure, then the dedicated test service was restored.

This implements the missing bounded economic experiment and exploratory handoff.
It does not establish that memory improves measured account performance. A fully
retained raw archive can still stop capture; a complete small historical interval
can be selected, but missing future packets are not reconstructed from prices.
Sufficient chronological executable training/calibration and a complete account
interval are actual data requirements. A short complete interval is not a multi-day
strategy result or 28-day qualification. Future paper outcomes, dependence,
opportunity coverage, host billing and economic advantage remain unverified.
