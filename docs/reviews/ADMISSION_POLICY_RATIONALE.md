# Admission policy rationale and evidence limits

October 6, 2026. This bounded source/history evaluation is pinned to accepted
base `6265240d64a932d987a763d106726675a1a18019`. It reuses the completed rollout
and identified retained evidence. This rationale performs no operating action;
implementation/test and installed evidence belong to the #66 checkpoint.
Chris subsequently authorized merging the reviewed integrated policy and trying
it together with the original unused trained-v2 task in one bounded experiment.
The packet, candidate, approved model profile and once-only limit remain unchanged.

## Latest user decision and source proposal

Chris confirmed the source-policy choice for draft #68: retain **100 ms as an
advisory whole-work target**, and block optional research on a **new duration
>=500 ms when at least four of the latest twenty work samples are >=500 ms**.
The repeated-pressure predicate requires a complete twenty-sample window;
exactly 500 ms counts, and a fast new pass cannot renew it from older slow
samples. Any **duration >=1,000 ms** remains an immediate severe trigger,
including before the window fills, with the **300-second severe recovery hold**
preserved. The 500-ms choice supersedes the earlier 250-ms blocking proposal
in this lane; it does not revise the historical percentile acceptance targets
below.

This is a **user-directed, uncalibrated source proposal**, represented by the
integrated policy in [`engine_diagnostics.py`](../../src/trading/engine_diagnostics.py).
Its installed status and actual coexistence evidence must be verified separately;
source fixtures do not demonstrate a safe model-admission threshold. The explicit
merge/combined-test instruction covers the changed guard for this one experiment,
without rewriting original authorization metadata. All independent guards, financial
authority and frozen account rules, current audit/freshness checks, disk/capture
protections, memory/profile/packet checks, twenty slots and storage policy remain
separate requirements. Candidate recovery parameters and procedural evidence
retain their stated source-only scope.

The 100-ms target measures preparation, financial transaction and post-commit
evidence capture together. It is not a measured order-response, feed-to-fill or
exchange execution deadline. Neither the inspected history nor matching-input
financial fixtures establish the effect of a 100-ms or 500-ms whole-work
boundary on win rate, profit or active-position protection. Unchanged financial
results under fixed inputs do not establish actual model coexecution capacity
or protection from contention under a new admission policy.

## What the existing numbers mean

At this base, `TieredPaperRuntime.observe_engine_work()` uses the entire completed
work interval: preparation, financial transaction and post-commit evidence
capture. The repeated-pressure condition requires a **new duration >100 ms**,
twenty retained work samples and **at least four >100 ms** in that window.
Samples need not be consecutive. Any **duration >=1,000 ms** independently
qualifies, including before twenty samples exist. A qualifying sample sets the
optional-research recovery deadline to **current monotonic time +300 seconds**.
Fast work does not renew or immediately erase that deadline.

The window counts completed observed work, not twenty seconds or every received
market message. Work cadence and flat-portfolio skipping affect its elapsed
span. The separate displayed engine percentile uses a longer bounded deque;
the four-of-twenty predicate does not calculate p95. See
[`tiered_runtime.py`](../../src/trading/tiered_runtime.py),
`observe_engine_work`, `run` and `snapshot`.

These numbers implement a **resource-pressure proxy and recovery policy for
optional work**. The source comment describes avoiding a single Windows
disk/scheduling outlier while demoting research for repeated pressure or a severe
stall. The guard continues financial processing; the pressure flag itself does
not stop the paper writer. That does not establish that the proxy is unnecessary
or that optional model work is safe when it is closed.

## Traceable origin and corrections

| Source reference | What is established | What is not established |
| --- | --- | --- |
| [`2446445`](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/commit/24464451818b8ffc4d5280142e268e4d02c9e85c), first imported reviewed source snapshot | All four numerical thresholds already exist. The imported `docs/STATUS.md` says live observation caught an overly sensitive guard; the imported feed/storage note says four-of-twenty avoids throttling on one brief disk/scheduler outlier. | Git does not contain the earlier patch or a derivation/calibration of these exact values. The note's later unconstrained point is not a matched risk/capacity study. |
| [`710050b`](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/commit/710050b6e4d7777259b98d0a56f466f5ce1187ad) | Adds phase/thread evidence, a twenty-sample diagnostic buffer, trigger counters and coalesced permanent notices. Thresholds remain unchanged. | Diagnostic coverage is not a complete work census or proof that the thresholds predict financial harm. |
| [`17b11e3`](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/commit/17b11e3007becca85c1352fbd8a111bcc72cd98b), #37 | Uses the high-resolution performance counter for the same complete guarded interval, separates transaction/capture phases and identifies current blocking conditions. | This corrects duration classification; it does not calibrate 100 ms or change the recovery rule. |
| [`49137cd`](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/commit/49137cd4761e1fdea5011c20aeeb60baee698ba4), #60 owner | Requires the **new** sample to exceed 100 ms, preventing old slow samples from extending recovery on a fast pass. Preserves 100/4/20/1,000/300. Moves financial readback to its read-only owner and retains audit-expiry refusal. | Faster observer responsiveness and a numerical CPU-placement result do not prove actual model coexecution or active-position protection. |
| [`65fc680`](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/commit/65fc680f1dff9aa7d08480e2c6b6c7bb17b49617), #63 | Makes current audit availability, confirmed negative results, notices and bounded readback shutdown agree. Historical balanced status cannot clear current unavailable monitoring. | It does not convert work duration into a measured host-pressure cause or recalibrate the latency policy. |

The imported contemporaneous rationale remains in
[feed/storage](../research/2026-09-27-feed-storage.md), “Promotion and demotion.”
The nearby [market-universe note](../research/2026-09-27-market-universe.md)
explicitly distinguishes a requested 100-ms book-stream cadence from an
execution-latency guarantee. The protocol interval is not a derivation of a
per-work admission deadline.

## Financial requirements versus the proxy

Financial correctness and responsiveness are real requirements: sole-writer
ownership; atomic accounting and invariant/journal checks; original account,
funding, risk and evidence preservation; fresh eligible inputs; protected
position handling; and explicit stale/error/unavailable/imbalanced refusal.
These are implemented through the existing financial/store/risk and monitor
owners. `LocalRoles.paper_guard()` requires running, error-free, non-stale paper
operation **and** unconstrained research; it is not replaced by a latency-only
check. `TieredPaperRuntime.constrained()` also includes disk reserve, capture
failure and current financial readback status. A confirmed negative audit stops
financial supervision; an expired/unavailable audit closes optional research.

There are also genuine **predeclared engineering acceptance targets**. The CP8
driver at [`c8c0060`](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/commit/c8c0060e53a80f9e8d297b5649f39626c3f29ca5)
declares commit p95 <=100 ms, p99 <=250 ms and maximum <=2,000 ms, plus dispatch,
queue, memory and CPU bounds. [CP8](../CP8_INTEGRATED_ACCEPTANCE.md) specifies
four shared synthetic book ticks/second, finite 1/10/20-account cases and a
predeclared five-minute soak. [CP16](../CP16_INTEGRATED_RESEARCH.md),
[its audit corrections](../CP16_AUDIT_CORRECTIONS.md),
[continuous Lab](../CONTINUOUS_PAPER_LAB.md) and
[CP23 acceptance](../CP23_ACCEPTANCE_PLAN.md) preserve loop/transaction
percentile requirements and retained failures.

Those declared targets matter within their stated verification scope. They are
not an economic calibration, an absolute guarantee that every financial action
finishes in 100 ms, or proof that four slow whole-work samples mandate a
five-minute model denial. The guard and the finite targets differ in interval,
population and statistic. No inspected history mathematically derives the
four-of-twenty, one-second or five-minute choices from the percentile targets,
market loss, freshness deadlines or measured incremental model harm.

## Retained evidence and its proper scope

| Retained observation | Supported conclusion and limits |
| --- | --- |
| #37 [reader/clock diagnosis](cp23/OPERATING_READER_RECOVERY.md): 150 coalesced receipts, 1,060 distinct selected samples, 49 coarse false-slow classifications and one missed precise slow classification | The previous clock misclassified short work; precise timing repairs that. Selected/coalesced samples are not the full duration distribution or evidence every denied admission was unnecessary. |
| #39 [inference-off ten-minute observation](cp23/OPERATING_PROJECTION_COMPRESSION.md): 185 healthy status polls, 981 distinct sampled work entries, 366 >100 ms, zero >=1 s; median/p95 89.674/173.079 ms | Healthy paper operation and a renewing pressure flag can coexist without model work. It does not establish safe spare capacity, causal CPU/memory/disk pressure or the effect of adding a trained model. Latest-window polling misses work and creates overlapping samples. |
| #45 [five-minute comparison](../RESEARCH_INTELLIGENCE.md): sampled whole-work median/p95 87.52/167.95 ms before and 89.48/179.05 ms after; 60/60 cooldown-active API samples in each window; post-update maximum 2,428.30 ms | A severe inference-off work interval was retained. Unequal incomplete coverage, uptime, input/workload and transport conditions preclude causal comparison or an exact stall/outage population. |
| #63 [bounded attribution observation](FINANCIAL_MONITORING_REPAIRS.md): 20.001 seconds, 37 distinct in-window work samples, seven >100 ms, zero >=1 s | Metadata/thread evidence did not identify a unique cause; observer overhead and missed alignment remain explicit. No installed financial-thread identity existed in that older receipt. It is not matched model-on/model-off evidence. |
| October 6 retained one-call guard at 00:52:14 UTC: 292.578-s cooldown, trigger 186, newest 102.131-ms pass and four slow samples in its trigger window; paper fresh/error-free and current audit balanced/available | Renewal is genuine under the corrected predicate. The later twenty samples span 10.819 s with one slow pass, median 70.706 ms and latest 71.311 ms. Transaction/read-decode/update/encoding dominate; one earlier selected capture contributes. This point proves the configured rule fired, not that an active-position deadline was missed or a model would have been safe. Zero model calls; the original attempt remains unused. |

The current diagnostic buffer retains only the latest twenty entries. Permanent
notices coalesce to at most one per minute while preserving trigger counts,
pending peaks and selected trigger windows. A trigger count is not a permanent
receipt count, unique severe-stall count or complete duration population.
Overlapping windows must be deduplicated; even deduplication cannot reconstruct
missed work. Before the #60 renewal correction, an old slow window could also
record a trigger on a fast current pass. Counters across policy versions must
not be reinterpreted as identical evidence.

The phase names bound attribution: read/decode includes SQL/transport/row lookup
and decoding; projection update includes its remaining client/server interval;
writer-lock wait is the Python RLock, not PostgreSQL row-lock waiting. Nested
phases overlap. Wall time minus charged thread CPU is not a measured database,
disk or scheduling wait. Sparse native or SQL snapshots cannot establish absence
of unsampled contention. No current projection size, cache-hit distribution or
whole-host capacity is invented from this trace.

## Evaluation boundary

The history provides a defensible conservative intent and corrections to actual
measurement/renewal faults. It does **not** provide retained calibration showing
this exact proxy separates safe and unsafe trained-model admission. That gap
neither disproves the protected-work requirements nor authorizes bypassing the
guard. This document changes no threshold, quota, financial control, profile,
qualification, model permission or activation state and makes no new operating
acceptance claim. Any source policy evaluation must retain those distinct
requirements and the original evidence, rather than relabel a heuristic as a
measured financial deadline or a healthy inference-off point as model capacity.
