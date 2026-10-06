# Bounded admission-policy evaluation — issue #66

The result is **one specified, tested offline policy candidate** following
Chris's latest decision: **100 ms is a target; new work at or above 500 ms blocks
research when four of the latest twenty observations are at or above 500 ms**.
This supersedes the draft's earlier 100-ms-trigger recovery candidate. It is
neither a measured performance repair nor installed coexistence acceptance.

The accepted rollout remains `6265240d64a932d987a763d106726675a1a18019` within its
documented scope. Its preservation/workflow receipt is reused. This evaluation
made no operating guard check, wait, update, restart, model call or original
attempt reservation. The original unused attempt still requires its unchanged
complete guard; this source policy decision does not amend its execution terms.

## Rationale and retained observations

[The source/history trace](ADMISSION_POLICY_RATIONALE.md) distinguishes financial
correctness and input freshness, declared performance targets, and a resource
pressure proxy. The original 100-ms/four-of-twenty, one-second and five-minute
settings already appear in the first imported snapshot. Later precise timing,
new-slow-pass renewal and #63 monitoring repairs are preserved. No inspected
evidence calibrates those exact values to incremental trained-model harm.

The new 500-ms choice is a **user-directed operating-policy proposal**, not a
derived financial deadline. The timer covers full completed processing work,
including database and evidence work; it does not directly measure signal-to-
order-start or fill latency. Neither these fixtures nor the retained records
demonstrate an effect on win rate. Any later adjustment needs actual comparable
latency/outcome evidence with workload, market conditions, failures and missing
coverage retained. Synthetic decisions cannot establish a trading edge.

The two immutable private receipts were read separately offline, without
joining their windows. The earlier 00:21 UTC receipt retains trigger 47 and a
twenty-sample current window with three >100-ms target misses. The latest
00:52 UTC receipt retains trigger 186 at **00:52:07.158167 UTC**, new work
**102.131 ms**, repeated pressure true under the installed policy, severe false.
Its trigger snapshot contains four slow samples of twenty; the sixteen other
trigger sample durations and timestamps are not retained. Those four retained
passes are all below 500 ms and would be advisory under the proposal.

The latest current window spans **10.819 wall-clock seconds**, with one >100-ms
target miss, zero >=500-ms observations and zero severe observations. All twenty
are below 500 ms. This is no longer disqualified merely by the earlier twelve-
sample <=100-ms suffix. Nevertheless, monotonic timestamps, prior severe state
and intervening observations are unavailable: **actual candidate admission is
unknown**, and no continuous recovery trace was replayed from wall-clock data.

The four triggering passes had no active portfolios. Transaction/read-decode,
update and encoding dominate; selected evidence capture contributes to one
pass. Nested intervals and coarse thread CPU do not isolate a unique database,
transport, CPU or disk cause. No speculative cache, serialization change or
database optimization was introduced. Trigger counts and minute-coalesced
notices do not count independent stalls or establish uninterrupted coverage.

## One candidate within the existing resource owner

`ModerateRecoveryCandidate` remains in
[`engine_diagnostics.py`](../../src/trading/engine_diagnostics.py). It has no
runtime call site, configuration flag, scheduler or model-admission integration.
`TieredPaperRuntime.observe_engine_work`, `constrained`, existing diagnostics
and `LocalRoles.paper_guard` remain unchanged. Its `pressure_would_allow` is
only a hypothetical latency-component result, never complete admission.

| Behavior | Current installed policy | Offline candidate v2 |
| --- | --- | --- |
| Performance target | >100 ms participates in blocking pressure | 100 ms is advisory; bounded target-miss count and observed denominator are reported separately |
| Moderate trigger | New >100 ms with at least four >100 ms in a complete latest-twenty window | New **>=500 ms** with at least four **>=500 ms** in a complete latest-twenty window |
| Moderate recovery | 300 seconds after latest qualifying slow work | Twenty consecutive valid **<500-ms** observations spanning at least ten seconds; each gap and latest age <=2 seconds |
| Isolated 500–999.999-ms work after recovery | Four-of-twenty must qualify | Four-of-twenty must qualify; an isolated pass interrupts any ongoing recovery coverage but does not demote an already recovered candidate |
| Severe trigger | Any new **>=1,000 ms**, including startup | Same; known severe evidence on an invalid clock stays latched |
| Severe recovery | Full 300 seconds, renewed by qualifying pressure | Full 300 seconds plus fresh recovery evidence; new qualifying >=500-ms repeated pressure during the hold renews it by 300 seconds |
| 100–499.999-ms work | Can create or renew blocking pressure | Does not trigger, reset recovery or renew a severe hold; contributes valid recovery observations |
| Fast new work with old slow samples | Cannot renew the old deadline | Cannot create a new trigger from old samples |
| Startup, missing/invalid work, clock regression, gaps >2 seconds | Separate existing status/financial gates apply | Latency candidate also remains closed until valid recovery coverage exists; known severe holds survive missing evidence |

The 500-ms boundary is inclusive. Exactly 100 ms meets the advisory target;
100.001, 250 and 499.999 ms do not block or interrupt recovery. Exactly 1,000 ms
is severe regardless of window size. Samples outside the latest twenty cannot
qualify a new repeated-pressure trigger.

The existing draft's **20-observation/10-second/2-second recovery bounds** remain
proposed QA parameters, not calibrated installed safety margins. Ten seconds
covers one paper-status freshness interval; two seconds permits ordinary flat
work near one-second cadence plus wake-up overhead. Counts alone are insufficient
because active passes can be much faster. Coverage ends at completed work, and
waiting cannot fabricate it. Untrusted-clock severe observations anchor the full
hold at the next trusted monotonic observation. State is bounded. No accounting
or evidence semantics, database or storage location changes.

## Revised isolated results

The [finite evaluator](../../scripts/evaluate_admission_recovery.py) compares
the actual unchanged current runtime observer with v2 using explicit synthetic
monotonic observations. Retained receipts are read within a two-MiB bound and
the new result is exclusively created. Input hashes match the previous
evaluation; v1 results and its 99-test receipt remain preserved as historical
evidence, not claimed as validation of v2.

| Fixture | Current pressure allows / observations | Candidate v2 allows / observations |
| --- | --- | --- |
| Normal work | 100 / 100 | 80 / 100 |
| Four 150-ms target misses, then 50-ms work | 24 / 125 | 105 / 125 |
| Four 600-ms blockers, then 150-ms work | 24 / 125 | 84 / 125 |
| Sustained 150-ms work | 19 / 200 | 180 / 200 |
| Sustained 600-ms work | 19 / 200 | 0 / 200 |
| One 1,000-ms stall, then 50-ms work | 2 / 602 | 2 / 602 |
| One 1,000-ms stall, then 150-ms work | 0 / 602 | 2 / 602 |
| Missing observation, then recovery | 43 / 43 | 2 / 43 |
| Twenty rapid startup observations | 20 / 20 | 0 / 20 |
| Repeated 600-ms interruptions with nineteen sub-500-ms passes between | 24 / 225 | 4 / 225 |

These are **counts at synthetic observation points**, not elapsed availability,
full-guard admission, measured model load or coexistence safety. Startup accounts
for twenty initially closed observation points at half-second cadence. In the
600-ms burst, the first recovered point occurs 10.5 seconds after the qualifying
trigger even though subsequent 150-ms work keeps renewing the installed policy.
The candidate never releases a severe hold before 300 seconds, and target misses
alone cannot renew that hold. Interrupted recovery is never pooled across gaps.

Six real `PaperEngine` traces each run with **both 150-ms and 600-ms bursts**:
active partial entry and paused-entry partial/full stop exits, pending fill,
operator cancellation, changed-filter cancellation, expiry and spread refusal.
Identical frozen inputs yield exactly equal states, events and book/feature
evidence even where pressure decisions differ. Assertions independently
reconstruct per-asset journal balances at every tick and retain expected Decimal
cash, fees, quantities, realized P&L, funding/risk policy, causal fills and no
repeated liquidity use. This is financial consistency proof, not measured
installed active-position latency or capture-file acceptance.

The revised locked CPython 3.12.10 selection passes **117 tests, zero skips,
zero warnings**, including boundary/recovery and retained-window cases, the
twelve financial cases, existing diagnostics/stream/engine tests, and unchanged
guard refusal before dispatch. Ruff passes the whole source/test tree and
evaluator; strict Windows-targeted mypy passes **108 source files**. Exact-head
hosted results and independent review are recorded in the #66 checkpoint.
Existing CI selectors/jobs and their lifecycle budgets remain intact.

Additional fixtures protect confirmed imbalance, missing/expired/error financial
monitoring, recording failure, disk reserves, stopped/stale/error paper, known
severe evidence on invalid clocks, long gaps and oscillation. Input eligibility,
writer/job ownership, storage roots and 400/100-GB policy, twenty-slot capacity,
fixed profile/model identity, CPU/RSS/reserve limits and #63 fixes retain their
existing owners. The revision had no focused-test failures; earlier setup/cache
failures, lint repairs and severity/bounded-read counterexamples remain retained
in v1 evidence. No completed operating suite or collector was repeated.

## Additional authority for one finite installed coexistence test

Chris has selected the **500-ms/four-of-twenty blocking policy**. That selection
does not authorize installing this offline evaluator or executing a model under
a changed guard. A separately reviewed runtime integration must preserve every
other guard, full-work monotonic evidence, severe recovery and the proposal's
specified recovery rules. Its exact reviewed head and passing checks require
bounded merge/update/restart approval using the existing owner and the guarded
full-SHA `ExpectedCommit` updater. This would be a new policy experiment, not a
repeat of the accepted 6265240 rollout or acceptance collector.

Actual coexistence additionally needs explicit authority to execute **under the
reviewed changed guard**. If using the original unused attempt, that amendment
must name its original task, packet and candidate, retain its approved profile,
and authorize one execution through `answer_development_role.py`. Until then,
the once-only permission still requires the unchanged installed guard. No new
question, preferred-answer retry, RAG, holdout, paid/external review, training or
promotion follows. Retain and reopen invalid, incomplete or failed outcomes too.

The proposed matched session remains **300 seconds model-off, one middle phase
of at most 600 seconds with at most one guarded child, then up to 300 seconds
recovery**, under one absolute **1,200-second** deadline. Reserve at least twenty
seconds within the middle phase for up to eight seconds of guard request and
ten seconds of owned-child cleanup. The unchanged 600-second model ceiling does
not alone enforce that total session budget. No repeated admission wait or
retry; entry refusal records its precise reason and ends without inference.
Early child termination, truncated recovery or deadline overrun retains actual
incomplete evidence rather than being classified as full acceptance.

Report matched whole-work/transaction p95 against the **100-ms target** and p99
against the historical 250-ms engineering target. Missing either target alone
is **not an admission refusal, test halt or claim of financial harm**. Apply the
new >=500-ms/four-of-twenty blocking rule and unchanged >=1,000-ms severe rule
to optional work, alongside financial monitoring/balance, paper freshness/error,
input eligibility, recording/storage, ownership and fixed model-resource guards.
Missing continuous observations or an unavailable audit prevents coexistence
acceptance. Synthetic availability cannot establish model capacity.

Classify natural workload by active positions/pending orders, frames, bars,
notices and capture. Unmatched phases cannot establish a performance repair or
win-rate effect. If natural active/pending processing is absent, disclose that
coverage without creating operating orders or altering financial policy. Stop
optional work on protected failure through its existing child owner; retain
legitimate appended history and the actual interruption rather than restoring
old data to manufacture a comparison.

Direct NAT socket association remains unresolved; populated Library/Review
acceptance remains unperformed. Neither is made true or requires repeating the
previous rollout. Compression, desktop packaging, another serving backend or
scheduler is not a prerequisite.
