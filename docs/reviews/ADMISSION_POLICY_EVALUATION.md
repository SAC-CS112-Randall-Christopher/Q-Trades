# Bounded admission-policy evaluation — issue #66

The result is **one specified, tested offline policy candidate**, not a measured
performance repair or installed coexistence acceptance. The accepted operating
rollout remains `6265240d64a932d987a763d106726675a1a18019`; its existing preservation,
workflow and recovery receipt is reused. No operating guard check, waiting cycle,
update, restart, model call or original-attempt reservation occurred in this
evaluation. The existing original attempt remains unused under its unchanged
authorization. This draft does not amend that authorization.

## Rationale and retained observations

[The source/history trace](ADMISSION_POLICY_RATIONALE.md) separates genuine
financial correctness, input freshness and predeclared engineering targets from
the pressure heuristic. All four original numerical choices already exist in
the first imported snapshot. Its rationale is tolerance of isolated scheduling
or disk outliers. Later precise timing, new-slow-sample renewal and current
financial-monitoring repairs are retained. No inspected evidence calibrates
four-of-twenty or five-minute recovery to measured incremental trained-model
harm. This uncertainty does not establish permission or spare capacity.

Two immutable private receipts were read offline, separately, without joining
their windows. The 00:21 UTC receipt retains trigger 47 and a twenty-sample
current window with three slow samples. The 00:52 UTC receipt retains trigger
186 at **00:52:07.158167 UTC**, new work **102.131 ms**, repeated pressure true
and severe false. The trigger retains four slow samples of twenty; its other
sixteen samples' durations/timestamps are not retained in that trigger snapshot.
The later current window spans **10.819 wall-clock seconds**, has one slow and
zero severe samples, and ends with **twelve** consecutive fast samples. The
earlier window ends with three. Neither supplies the candidate's required twenty
consecutive calm observations. Monotonic sample timestamps and intervening
history are unavailable, so neither window was replayed as a continuous trace.

The four triggering passes had no active portfolios. Transaction/read-decode,
update and encoding dominate; selected evidence capture contributes to one
pass. These nested intervals and coarse thread CPU do not identify a unique
database, transport, CPU or disk cause. No speculative performance correction
is justified by those observations. Earlier sparse observations and retained
severe stalls remain described in the rationale; trigger counters and coalesced
notices are not independent-stall counts or an uninterrupted work census.

## One candidate within the existing resource owner

`ModerateRecoveryCandidate` resides in the existing
[`engine_diagnostics.py`](../../src/trading/engine_diagnostics.py) owner. It is an
offline evaluator with no runtime call site, configuration flag, scheduler or
model-admission integration. `TieredPaperRuntime.observe_engine_work`,
`constrained`, all existing diagnostics and `LocalRoles.paper_guard` are
unchanged. The evaluator returns only `pressure_would_allow`; this is never a
complete admission decision.

| Behavior | Current installed policy | Offline candidate |
| --- | --- | --- |
| Moderate trigger | **New >100 ms**, at least four >100 ms in the last twenty completed work observations | Same trigger and strict boundaries |
| Moderate recovery | 300 seconds after the last qualifying new slow pass | At least twenty consecutive completed observations **<=100 ms**, spanning at least **10 seconds**, each gap **<=2 seconds**, latest age **<=2 seconds** |
| Severe trigger | Any new work **>=1,000 ms**, including startup | Same threshold; malformed-clock severe evidence remains latched |
| Severe recovery | Full 300 seconds, renewed by any qualifying pressure | Full 300 seconds plus fresh calm recovery evidence; qualifying moderate pressure during the severe hold still renews it by 300 seconds |
| Newly fast work | Cannot renew the old deadline | Contributes only explicit measured calm evidence |
| Isolated slow work after recovery | Does not trigger unless four-of-twenty qualifies | Same; it interrupts any ongoing calm evidence and cannot be pooled across recovery epochs |
| Startup, absent/invalid observations, clock rollback, long gap | Latency component alone has no observation-coverage test; separate existing status/financial gates remain | Candidate closes until fresh calm coverage exists; it preserves known severe holds across missing observations |

The **10-second** minimum covers one existing paper-status freshness interval;
the **two-second** gap ceiling permits ordinary flat-portfolio work at about
one second plus wake-up overhead. Both are explicitly proposed test parameters,
not existing financial deadlines, calibrated operating safety limits or proven
model-capacity margins. Twenty observations alone are insufficient because
active passes can be much faster than flat commits. Coverage ends at the latest
completed observation; evaluation-time passage cannot fabricate calm coverage.
Invalid-clock severe observations anchor the full hold at the next trusted
monotonic observation. Boolean/nonfinite/negative duration evidence cannot
establish recovery. All state is bounded, and no accounting/evidence payload is
cached, serialized differently or moved to another database.

## Isolated results and protected financial behavior

The checked-in [finite offline evaluator](../../scripts/evaluate_admission_recovery.py)
uses the actual current runtime pressure observer without constructing its
services, and the candidate with explicit synthetic monotonic observations.
It reads each retained receipt within a two-MiB bound and writes a new result
exclusively. Private input hashes and the full result are retained outside Git.

| Fixture | Current pressure allows / observations | Candidate pressure allows / observations | Meaning |
| --- | --- | --- | --- |
| Normal completed work | 100 / 100 | 80 / 100 | Candidate first establishes startup calm evidence |
| Four moderate passes, then calm | 24 / 125 | 84 / 125 | Eighty observation points show earlier hypothetical recovery; first release is 10.5 seconds after the qualifying trigger, with 289.5 seconds remaining under current policy |
| Sustained 150-ms work | 19 / 200 | 0 / 200 | Current latency component waits for twenty samples; candidate startup/pressure never opens |
| One 1,000-ms stall, then calm | 2 / 602 | 2 / 602 | Neither releases before the full 300-second severe hold |
| Missing observation, then calm | 43 / 43 | 2 / 43 | Candidate discards earlier calm evidence and rebuilds it |
| Twenty rapid startup observations | 20 / 20 | 0 / 20 | Sample count cannot substitute for elapsed measured coverage |
| Repeated interrupted recovery | 24 / 225 | 4 / 225 | Neither recovers after the moderate trigger; candidate never pools interrupted calm runs |

These are **counts at declared synthetic observation points**, not wall-time
availability, complete-guard admission, measured load or a model-capacity result.
No synthetic CPU stressor or trained model ran. The candidate can still repeatedly
admit after calm and then encounter pressure when optional work starts; the
fixtures cannot establish whether its ten-second hysteresis is sufficient in
the operating installation.

Six matched traces exercise the real `PaperEngine`: active position with partial
entry and paused-entry stop exits, pending fill, operator cancellation,
changed-filter cancellation, expiry and spread-based refusal. Both histories
receive identical frozen inputs. The pressure policies differ after moderate
recovery while financial states, events and book/feature evidence remain exactly
equal. Independent assertions reconstruct per-asset journal balances at every
tick and verify expected Decimal cash, fees, quantities and realized P&L,
unchanged funding/risk policy, causal fills and no repeated liquidity use.
These are synthetic financial consistency tests; they do not prove durable
operating prefixes, capture-file recovery or installed active-position latency.

Additional fixtures exercise severe/moderate interleaving, renewal, exact
thresholds, missing/negative/nonfinite/boolean evidence, regressed/duplicate
clocks, long gaps, recovery without fresh work and repeated oscillation. Actual
`constrained()` and mocked ordinary `LocalRoles.paper_guard()` retain independent
imbalance, unavailable/expired/error monitoring, disk reserve, recording failure,
stopped/stale/error paper and current research-pressure refusal. Existing input
eligibility, sole-writer/job ownership, storage roots and 400/100-GB policy,
twenty-slot capacity, fixed model/profile identity, CPU/RSS/reserve limits and
#63 monitoring repair remain with their existing owners.

The final locked CPython 3.12.10 native selection passed **99 tests, zero skips,
zero warnings**, including the new policy/receipt/financial fixtures, existing
engine diagnostics/stream and deterministic-engine cases, and original guard
refusal before dispatch. Whole source/tests plus the evaluator pass Ruff;
strict Windows-targeted mypy passes all **108 source files**. The offline
evaluation was reopened after the bounded-read repair and reproduced the same
result from the same immutable input hashes. Exact published head/checks are
recorded in issue #66; these focused checks are not a new full acceptance suite.
The initial sandboxed run failed because pytest could not access its disposable
temporary directory and then failed during cleanup. A fresh authorized native
QA run corrected that harness access. The separate financial run passed six
tests with a cache-permission warning; the final run disables that cache. Those
setup failures are retained rather than counted as passing product evidence.
Three initial evaluator line-length lint errors were corrected before the final
passing lint. Independent review also found and repaired the untrusted-clock
severe-event loss and the initial receipt read-before-size-check defect; their
counterexample/oversize fixtures pass. The explained empty pytest cache artifact
was moved into the private evidence directory with its resolved source and
destination bounded to this task. The source lane is clean of that artifact.
No desktop, installer, rollout collector or completed operating acceptance suite
was repeated.

## Exact additional decision for finite installed coexistence

This draft can be reviewed as a proposal. **It cannot install a new guard or
execute a model.** Before any installed test, Chris must explicitly approve the
candidate recovery rule and its 20/10/2 bounds as an experimental admission
policy. A separately reviewed runtime integration must preserve every other
complete guard and retain monotonic full-work observations. Its exact reviewed
head and passing checks then need bounded merge/update/restart approval through
the existing sole owner and guarded `ExpectedCommit` updater. This would be a
new policy experiment, not a repeat of the completed `6265240` rollout or its
acceptance collector.

An actual trained-model coexistence test additionally needs **explicit authority
to execute under this changed guard**. If Chris elects to use the original
unused attempt, the amendment must name that original task/packet/candidate and
unchanged approved profile, and authorize its one execution through
`answer_development_role.py` under the specifically reviewed candidate policy.
Until that explicit amendment, the existing once-only permission continues to
require the unchanged current guard. It cannot be used to test this candidate.
No RAG, new question, retry, qualification holdout, paid/external review or model
promotion follows from either decision.

The proposed finite test is one matched session: **300 seconds model-off,
one middle phase capped at 600 seconds including at most one guarded development
child, then up to 300 seconds recovery**. Future test integration must enforce
**one absolute 1,200-second session deadline**, with no unchanged admission wait
or retry. Reserve at least **20 seconds inside the middle phase** for the
existing up-to-eight-second guard request and up-to-ten-second owned-child
cleanup; stop new dispatch/continuation early enough to fit that reserve. The
unchanged 600-second child/profile ceiling alone does not enforce the session
cap. The experiment budget may stop its child earlier, retaining the actual
incomplete outcome. The session clock includes guard and shutdown overhead;
any truncated recovery or deadline overrun is incomplete evidence, never a
claimed full recovery pass. If the full
experimental guard, original identity/unused allowance, fixed profile, ownership
or reserves refuse at entry, retain the exact refusal and stop without inference.
Use the existing process owner, read-only audit and saved result/attempt ledger.
Retain every actual outcome, including invalid, incomplete or failed answers.

Predeclare and measure matched financial whole-work and transaction p95 <=100 ms,
p99 <=250 ms, no whole-work stall >=1,000 ms, unchanged freshness/input eligibility,
zero confirmed imbalance, recording/storage reserves and fixed model-resource
limits. Missing continuous work observations or an unavailable audit makes
coexistence acceptance unavailable. Classify phases by natural workload
(active positions/pending orders, frames, bars, notices and capture); unlike
workloads cannot support an optimization claim. If no natural active/pending
processing occurs, disclose that coverage as untested instead of creating orders,
changing financial rules or corrupting operating data. Stop optional work on any
protected-condition failure; the existing supervisor owns only its own child.
Report the actual interruption and retained history; do not roll back legitimate
appends to manufacture a comparison.

Installed source identity, preservation and ordinary navigation use the existing
receipt/procedure; any newly required policy-test observation is separate. The
direct NAT socket association remains unresolved, and populated Library/Review
acceptance remains unperformed. Neither is silently made true or used as a reason
to rerun the previous rollout. No compression, desktop packaging, new backend or
scheduler is a prerequisite for the policy decision.
