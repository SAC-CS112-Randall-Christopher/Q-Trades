# Bounded admission policy and combined test — issue #66

Chris selected **100 ms as an advisory target** and **new work >=500 ms as a
blocker when at least four of the latest twenty observations are >=500 ms**.
The first offline revision was verified at c45d760. Chris then authorized:
**"Merge when ready and then try it working all together."** The successor
integrates that policy into the existing resource owner and provides one finite
original-task coexistence experiment. Source, installed, actual-model and
trading-outcome proof remain separate.

The accepted rollout at `6265240d64a932d987a763d106726675a1a18019` stays complete
within its documented scope. Its receipt and established preservation procedure
are reused. This new policy experiment is not a repetition of that acceptance,
nor authority for compression, desktop packaging or operating-role activation.
Actual merged/installed targets and experiment results belong in the #66 ledger.

## Evidence and meaning of the target

[The rationale](ADMISSION_POLICY_RATIONALE.md) traces the original settings,
precise timing, new-slow-pass renewal and #63 financial-monitoring repairs.
It distinguishes financial correctness/freshness, declared engineering targets
and a resource-pressure heuristic. The exact original thresholds are not
calibrated to measured incremental trained-model harm. The selected 500-ms
boundary is user-directed, not a demonstrated financial deadline.

Whole-work time includes preparation, the financial transaction and post-commit
evidence work. It is not direct signal-to-order-start or fill latency. Neither
synthetic fixtures nor the retained records establish an effect on win rate.
Future changes need matched actual latency/outcome evidence with workload,
market conditions, failures and incomplete coverage retained. No speculative
cache, serialization change or database optimization was introduced.

Two immutable private receipts were reopened separately offline, without
stitching their windows. The earlier 00:21 UTC receipt retains trigger 47 and
three >100-ms samples in its current twenty. The latest retains trigger 186 at
**00:52:07.158167 UTC**, **102.131-ms** new work, repeated pressure true under
the accepted baseline and severe false. Its trigger contains four slow passes,
all below 500 ms; the other sixteen durations/timestamps were not retained.

The latest current window spans **10.819 wall-clock seconds**, with twenty
<500-ms samples, one >100-ms target miss and zero severe observations. Its old
twelve-sample <=100-ms suffix is no longer a blocking criterion. Nonetheless,
monotonic timestamps, prior severity and intervening work are unavailable:
**actual candidate admission from these retained windows is unknown**.
Trigger186 does not represent 186 independent stalls, and minute-coalesced
notices do not establish an uninterrupted work census.

Those triggering passes had no active portfolios. Nested transaction/read-decode,
update, encoding and selected capture intervals, plus coarse CPU measurements,
do not identify a unique contention cause. The original records and earlier
severe-stall evidence retain their stated limits.

## Integrated resource policy

`EngineWorkPressurePolicy` in
[`engine_diagnostics.py`](../../src/trading/engine_diagnostics.py) is the existing
runtime's latency component. A single `_work_pressure` instance replaces the
duplicated cooldown state in observation, `constrained` and status snapshots.
`pressure_allows` is only a component result, never complete admission.
There is no competing scheduler, serving backend, bypass flag or financial owner.

| Behavior | Accepted 626 baseline | Integrated v3 |
| --- | --- | --- |
| Target | >100 ms participates in blocking pressure | 100 ms advisory; report target misses and observed denominator |
| Moderate trigger | New >100 ms and >=4 of complete latest 20 >100 ms | New **>=500 ms** and >=4 of complete latest 20 **>=500 ms** |
| Moderate recovery | 300 seconds after latest qualifying work | 20 consecutive valid **<500-ms** observations spanning >=10 seconds, gaps/latest age <=2 seconds |
| Isolated500–999.999-ms work after recovery | Four-of-twenty must qualify | Same; interrupts ongoing recovery coverage but does not demote an already recovered policy |
| Severe trigger | Any new **>=1,000 ms**, including startup | Same, with invalid-clock severity latching |
| Severe recovery | Full300 seconds, renewed by qualifying pressure | Full300 seconds plus fresh recovery evidence; new qualifying >=500-ms repeated pressure during it conservatively renews the full hold |
| 100–499.999-ms work | Can create/renew blocking pressure | Contributes to recovery; never triggers, resets recovery or renews a severe hold |
| Fast new work | Cannot trigger from old slow samples | Same |
| Startup/missing/invalid work, clock regression, gaps >2s | Separate financial/status gates | Policy also closes until valid recovery coverage; known severe holds survive missing observations |

Exactly 500 ms counts; exactly 1,000 ms is severe independently of window size.
The 20/10/2 recovery bounds remain proposed, uncalibrated parameters: ten seconds
covers one paper-status freshness interval, while two seconds accommodates
ordinary near-one-second flat work. Counts cannot substitute for measured time.
Waiting alone cannot produce recovery coverage. Invalid-clock severe evidence
anchors the full hold at the next trusted monotonic observation.

Bounded twenty-sample diagnostics now include protected monotonic timestamps,
cumulative work numbers and the existing process-instance epoch. The finite
observer can deduplicate overlap and disclose dropped sequences/restarts rather
than infer coverage. Versioned notices distinguish >100-ms advisory windows
from >=500-ms blocking windows. No new financial cache or history buffer exists.
Independent imbalance/current-audit, freshness/error, input, recording/storage,
ownership and fixed model safeguards remain with their existing owners.

## Isolated proof and its limits

The [offline evaluator](../../scripts/evaluate_admission_recovery.py) compares
a pinned 626 pressure reference with the actual integrated policy. The reference
is confined to scripts/tests and cannot govern production admission. It reads
each retained receipt within two MiB and writes results exclusively. Original
input hashes and v1/v2 receipts remain preserved. Old green heads never replace
verification of the final integrated head.

| Fixture | Baseline allows / observations | v3 allows / observations |
| --- | --- | --- |
| Normal work | 100/100 |80/100 |
| Four 150-ms passes then 50-ms work |24/125 |105/125 |
| Four 600-ms passes then 150-ms work |24/125 |84/125 |
| Sustained 150-ms work |19/200 |180/200 |
| Sustained 600-ms work |19/200 |0/200 |
| One 1,000-ms stall then 50-ms work |2/602 |2/602 |
| One 1,000-ms stall then 150-ms work |0/602 |2/602 |
| Missing observation then recovery |43/43 |2/43 |
| Twenty rapid startup observations | 20/20 |0/20 |
| Repeated 600-ms interruptions separated by 19 sub-500 passes |24/225 |4/225 |

These are synthetic observation-point counts, not elapsed availability, complete
admission or model capacity. Moderate recovery after a 600-ms burst first occurs
10.5 seconds after its qualifying trigger, even with 150-ms target misses. No
severe release occurs before 300 seconds. Interrupted runs are not pooled.

Six real `PaperEngine` traces each run with 150-ms and 600-ms bursts: active
partial entry/paused-entry partial and full stop exits, pending fill, operator
cancellation, filter cancellation, expiry and spread refusal. Frozen financial
inputs yield identical states/events/book evidence where pressure decisions
differ. Independent per-tick journal/Decimal assertions preserve cash, fees,
quantity, realized P&L, funding/risk, causal fills and single liquidity use.
These twelve cases prove consistency, not measured operating-position latency.

V2 passed 117 locked native tests without skips/warnings and six exact-head
c45d760 hosted checks: native 700 passed/220 skipped/1 warning, PostgreSQL 1149
passed/89 skipped/1 warning, runtime ownership 73 passed, persistent research 75
passed/1 warning, dashboard and browser monitoring passed. Final integrated
native/static/hosted counts, independent review and retained failures are recorded
in #66. New runtime/status/notice, sequence coverage and cancellation fixtures
must pass before merge. Hosted skips remain unexecuted coverage.

The integrated runtime's initial checks retained a floating-point assertion
failure and temporary-path setup failures. Approximate arithmetic assertion and
fresh authorized QA-directory setup corrected them. Earlier v1 cache/setup,
lint, invalid-clock severity and bounded-read findings remain retained. The
source lane does not rebuild the accepted rollout collector or repeat its suite.

The integrated local runtime/financial fixture selection passed **144 tests**, with
**39 PostgreSQL cases skipped** because the explicitly selected local database
configuration is absent, and one existing Starlette dependency warning. Whole
source/script lint and Windows type checks passed (108 source files). The hosted
full PostgreSQL job must execute those cases at the final head before merge.

Independent review reproduced a Windows monotonic-clock tie: the first candidate
rejected distinct completed work with equal timestamps, falsely erasing calm
coverage. It now accepts nondecreasing clocks while work numbers preserve unique
observations; twenty equal timestamps still lack the required ten-second span.
The three failing runtime counterexamples and their repaired 80-test selection
are retained. Review also found missing initial session coverage in the observer;
the counterexample initially failed and is retained. The repaired observer now
records an unknown/missing initial prefix unless it is proved historical. Its
final isolated selection passed **28 tests**, with **one real-worker PostgreSQL
case skipped locally**, zero warnings and zero failures. That case remains a
final-head hosted PostgreSQL prerequisite. The observer also retains bounded
failure reasons and explicit deadline-overrun/incomplete flags.

## Authorized operating sequence and finite budget

The human merge/combined-test instruction covers the reviewed integrated policy,
guarded operating update and one original-task experiment under that policy.
The sole existing rollout owner must verify exact head/review/check applicability,
record the actual merged commit and confirm merged content/checks. The supported
updater receives that full SHA in `ExpectedCommit`; its own fetch must match
before build, backup or shutdown. Preserve financial prefixes and legitimate
appends, accounts/funding/configuration/evidence/private artifacts, twenty slots
and 400/100-GB policy. Verify intended task/process/database/storage before/after
handoff and disclose the actual interruption. Never guess a database writer
from mismatched NAT ports or kill an unassociated session.

The original task is `role-3dc561bf69b31ba6fb55ed87f0ee3662`. Immediately recheck
unused task/attempt/allowance state, original packet, trained-v2 candidate,
unchanged approved profile and the complete installed guard. Existing or
uncertain dispatch requires reconciliation; closed entry ends without waiting
or retry. Use [`answer_development_role.py`](../../scripts/answer_development_role.py)
once. Original authorization/admission metadata is retained. No new question,
RAG, holdout, training/download/conversion, paid/external review, promotion,
financial-policy change or operating-role activation follows. Retain and reopen
the actual raw/result/failure, including invalid and incomplete outcomes.

One matched session has **300 seconds model-off**, a **<=600-second middle
phase** containing at most one child and **>=20 seconds reserved** for guard
requests and owned-child cleanup, then **<=300 seconds recovery**, under one
absolute **1,200-second** deadline. The optional explicit CLI cancellation
deadline uses existing transport cancellation and receipt retention; it does
not rewrite the 600-second profile. The read-only observer dispatches nothing.
Timeout/abort, truncated recovery, missed work or failed cleanup remains actual
incomplete evidence. There is no admission-wait or preferred-answer retry.

Report whole-work/transaction p95 against 100 ms and p99 against the historical
250-ms engineering target. Target misses alone do not block or prove harm.
Apply the 500-ms/four-of-twenty and one-second severe rules to optional work,
alongside every independent financial/resource guard. Missing continuous work
coverage or unavailable audit prevents coexistence acceptance. Actual child
overlap/resource identity must come from the owned transport/result, not merely
request time. Classify natural active positions/pending orders, frames/bars,
notices/capture; absent natural cases remain untested. Unmatched workloads cannot
establish a performance repair or win-rate effect. Preserve legitimate appends.

Direct NAT association remains unresolved. Populated Library/Review acceptance
remains unperformed. Neither becomes true or requires a repeat of 626 acceptance.
Compression, desktop packaging, another backend or scheduler is not a prerequisite.
