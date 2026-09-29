# Local research-role qualification checkpoint

September 28, approximately 13:23 Denver: the restarted batch is terminal. It stopped
at 13:07:35 when cumulative resource waiting reached 1,800.047 seconds. Trainer and
reviewer development each passed 4/4. Trainer holdout completed eight passing responses,
with no failed/incomplete responses or critical violations; 28/36 are untested.
Reviewer holdout never began. The project qualifier independently rejects trainer
for missing scenario/seed coverage and reviewer for missing holdout evidence.
No role is qualified. The eighth explanation correctly rejects final-test reuse.
Holdout latency was 233.688-354.359 seconds, median 323.0855 seconds.

Five waits recovered; the sixth stopped before `holdout-trainer-split_overlap` was
dispatched. No request was in flight at shutdown. Queue/evaluator processes are gone;
both project services remain running. All 16 development/holdout rows were independently
checked, and the original imported prefix, full development receipt, frozen source bytes
and 12-file source archive verify unchanged. Existing rationale caveats and prior failures
remain. The 15-minute watcher is paused; the four-hour follow-up remains active.
Next work is investigation of recurrent paper-engine cooldowns before any new frozen
continuation, preserving all eight holdout answers and exhausted wait history.
See [terminal review](2026-09-28-1323-model-result.md) and
`qualification-qwen14b-resume-20260928T173007Z.terminal.json`.

September 28, approximately 13:04 Denver: trainer holdout coverage reached 7/36,
all independently passing with valid CPU placement and paper-health samples.
The newest answers correctly rejected a late-arriving predictor and preprocessing
fitted across training/validation/test data, in 326.187 and 296.813 seconds respectively.
The eighth request, `holdout-trainer-search`, began at 13:00:46 and remains active.
Five resource waits have recovered; cumulative usage is 1,745.657 of 1,800 seconds,
leaving 54.343 seconds. No budget was reset or enlarged. Original prefix, complete
development receipt, prior holdout checks and frozen files remain unchanged.
Reviewer holdout is pending; no role qualifies. Both tasks and follow-ups remain active.
Paper remains running/fresh with a balanced journal, 19 closed trades and primary
equity $97.5097533402. ArcGIS request latency remains unmeasured. Evidence:
`model-watch-20260928T1901.json` and its process snapshot.

The paper guard uses a five-minute cooldown after repeated slow engine work or one
severe stall, plus disk/capture checks. Aggregate p95 measurements do not identify
which samples caused the cooldown. If waiting exhausts the frozen allowance, retain
the incomplete result and investigate that workload before changing any subsequent
resource policy; do not bypass this active gate.

September 28, approximately 12:49 Denver: trainer holdout coverage reached 5/36,
all independently passing contract, citation, expected-decision, CPU-placement and
paper-health checks. The newest answers correctly requested matured 60-minute labels
and identified 42 samples as below the supplied 300-sample minimum. They completed in
337.937 and 319.984 seconds. A third resource wait recovered after 391.032 seconds;
cumulative stage waiting is now 1,474.392 of 1,800 seconds, leaving 325.608 seconds.
The sixth request, `holdout-trainer-late_feature`, began at 12:45:51 and remains active.
No role qualifies and reviewer holdout is pending. The original prefix, complete
development receipt, earlier holdout checks and frozen files remain unchanged. Both
tasks and follow-ups are active; paper remains fresh/running with a balanced journal.
There was no restart or new inference from this monitor. Evidence:
`model-watch-20260928T1846.json` and its process snapshot.

September 28, approximately 12:34 Denver: the second resource wait recovered
automatically at 12:28:22 after 677.188 seconds. Trainer case
`holdout-trainer-pending_labels` is now in flight. Completed coverage remains 3/36,
all passing on independent checks; reviewer holdout has not started. The two completed
waits consumed 1,083.360 cumulative seconds of the 1,800-second stage allowance.
Both project tasks, queue/evaluator and original paper worker remain alive. Current
server/model-worker identity, IDLE priority, affinity and zero GPU placement verify.
Paper is running/fresh with a balanced journal, though its optional-research constraint
has returned during the admitted request. The gate acts between requests.
Original prefix, full development receipt and frozen files remain unchanged.
No role qualifies and no inference was repeated by this monitor. Both follow-ups
remain active. Evidence: `model-watch-20260928T1831.json` and its process snapshot.

September 28, approximately 12:19 Denver: the first real resource wait resumed
automatically at 12:11:21 after 406.172 seconds. The third trainer holdout answer
then passed in 344.328 seconds; all three completed holdout answers were independently
checked against the contract, citations and expected decisions, with valid CPU placement
and healthy paper-worker samples. The new final explanation correctly distinguishes
the 60-minute forecast horizon from the matching purge and retains separate training-only
preprocessing and test-isolation requirements. Coverage is still only 3/36.

A second resource wait began at 12:17:05 before `holdout-trainer-pending_labels`;
511.453 cumulative wait seconds had been used at this snapshot. Queue/evaluator and
both project tasks remain alive, with no request in flight and no trading model resident
during the wait. The entire development receipt, original imported answer and frozen
files remain unchanged. Trainer/reviewer development scores remain 4/4 each; reviewer
holdout is pending and no role qualifies. This confirms recovery between requests,
not in-flight preemption or measured ArcGIS request latency. No service was restarted.
Both follow-ups remain active. Evidence: `model-watch-20260928T1816.json`.

September 28, approximately 12:08 Denver: the combined development receipt finished
at 11:55:43. Trainer and reviewer each passed 4/4 independently recomputed checks,
with no critical violations and verified CPU placement/paper health for every answer.
Median response times were 269.1485 seconds for trainer and 160.461 seconds for reviewer.
The original answer, source hash and all frozen files remain unchanged. The reviewer's
valid-case rationale loosely groups separate preprocessing/test-isolation safeguards
under chronological purging; retain that caveat alongside the original trainer caveats.
Stored scores have not been regraded.

Trainer holdout began at 11:56:18, receipt `research-roles-holdout-20260928T175618Z.json`.
Its first two answers passed in 261.953 and 233.688 seconds. Before the third request,
the evaluator entered a persisted resource wait at 12:04:35; 150.469 seconds had accrued
at the 12:07 snapshot. The queue/evaluator remain alive, with no active request and
no trading model resident during the wait. This is the first observed real wait under
the new continuation policy; a successful recovery has not yet been observed.
Reviewer holdout has not run. No role qualifies from this incomplete coverage, and no
agent was enabled. Paper remains running/fresh with a balanced journal. Both project
tasks and both follow-ups remain active. ArcGIS was preserved; concurrent response
latency remains unmeasured. Evidence: `model-watch-20260928T1801.json` and its process
snapshot. Leave the active frozen run untouched.

September 28, approximately 11:48 Denver: the restarted receipt now has four correct
trainer development answers, independently checked against the contract and expected
outputs with no critical violations. The three new responses took 290.516, 247.781
and 218.844 seconds; their final explanations correctly identify future-feature
leakage, unavailable outcome labels and unequal costs. The original valid answer's
terminology caveats remain. Its prefix and source hash are unchanged. The first
reviewer request is active; no holdout has run and no role is qualified. The combined
stage is still active, so no terminal certificate is produced. No resource waiting
has occurred in this continuation yet. See `model-watch-20260928T1746.json` and
current STATUS; leave the active frozen run untouched.

September 28, approximately 11:32 Denver: Chris requested restarting the batch.
`qualification-qwen14b-resume-20260928T173007Z` now evaluates the first unrun trainer
case after importing the original completed answer unchanged. The new source archive
adds explicit resource-stop continuation and bounded waiting/recovery. Model prompts,
settings, CPU profile and qualification gates are unchanged. No new answer has
completed at this checkpoint. The completion watcher is active again. See
[recovery behavior and verification](2026-09-28-resource-resume.md) and current status.

September 28, approximately 11:05 Denver: the remaining-roles batch is terminal.
One trainer development answer passed in 297.172 seconds; the paper resource guard
then stopped evaluation. Trainer coverage is 1/4 and reviewer 0/4, with no holdouts.
Both roles were checked using the qualifier and cannot qualify. The final rationale
has terminology caveats recorded separately from its passing structured score.
All receipts and source archives are preserved. No evaluation is active now. See
[the terminal review and next step](2026-09-28-1100-model-result.md).

September 28, approximately 10:40 Denver: the first elastic batch stopped at 10:23
after one completed researcher answer (442.235 seconds, 751 generated tokens) that
failed the contract by inventing a missing-data defect. Runtime placement also
failed because both PowerShell supervisors had exited with control-interruption
code `0xC000013A`; the source is unknown. Its original answer, failed score, source
archive and `qualification-qwen14b-elastic-20260928T161443Z.terminal.json` remain.
No role qualified. The researcher answer will not be retried to obtain a pass.

Both supervisors now use the tested windowless `service_host.py`. The separately
frozen `qualification-qwen14b-remaining-20260928T163843Z` batch tests only the
previously untested trainer and reviewer, then holdouts only after complete 4/4
development screens. Prompts, seeds, decoding, six-thread CPU policy, timeout and
correctness gates are unchanged. Source changes add fresh supervision checks before
dispatch, a declared role subset and windowless evaluator launch. Its state is
`data/qualification-qwen14b-remaining-20260928T163843Z.state.json`; at this checkpoint
it waits for the paper resource guard, with no inference yet. Queue processes can
be pythonw.exe: inspect both Python executable names before any stop operation.
Preserve this batch's frozen files. See current [status](../STATUS.md).

At 10:42:04 the paper guard cleared and the trainer/reviewer development stage
started (evaluator launcher 33452). No answer has completed at this checkpoint.

The following checkpoints are historical.

September 28, approximately 10:22 Denver: the initial CPU batch terminated with one
600.015-second incomplete researcher development response and a subsequent paper
resource constraint. No trainer/reviewer request ran. Negative qualification checks
and all failures are retained in `qualification-qwen14b-cpu-20260928T154037Z.terminal.json`.
The two complete earlier researcher receipts were rechecked: Qwen3 8B 32/36 and
Qwen3.5 4B 33/36, both below the unchanged 34/36 gate. No role is qualified.

The new resource allocation has an independent freeze/source archive:
`docs/evidence/qualification-qwen14b-elastic-20260928T161443Z.json`. Active state is
`data/qualification-qwen14b-elastic-20260928T161443Z.state.json`; its first development
stage began at 16:15:46 UTC. It uses six CPU threads, all processors eligible and
IDLE priority, with actual Windows process identity/priority/affinity checks and
zero-GPU placement required for qualification. The role prompts, scenarios, seeds,
decoding, 600-second allowance and correctness gates are unchanged. Repeated
development scenarios under this different resource profile are not independent
reasoning evidence. Do not alter its frozen files or start overlapping inference.

The 71.329-second, 2.799-token/second counting probe is infrastructure evidence only.
The CPU profile can receive spare scheduler capacity; GPU handoff and simultaneous
ArcGIS inference latency remain unverified. Both tasks are Running at this checkpoint;
the paper worker was never restarted. See [the heartbeat audit](2026-09-28-0954-heartbeat.md).

September 28, approximately 09:50 Denver: the dedicated batch is now evaluating,
with its first researcher request started at 15:43:43 UTC. No completed response
or qualification is available at this checkpoint. Its fixed CPU allocation remains
unchanged while Chris's later elastic-resource direction is recorded for subsequent
implementation in [the priority policy](2026-09-28-resource-priority.md).

September 28, approximately 09:42 Denver: Chris authorized a dedicated runtime
for concurrent ArcGIS and trading work. The original 14B queue was superseded
before its first inference request, with its original freeze/state retained. The
replacement CPU-only profile uses port 11435, two logical processors, lower worker
priority and a predeclared 600-second request allowance. Prompts, corpus, decoding,
output budget and correctness gates are unchanged; all three roles must undergo
development screening again before conditional holdouts. Slow model latency is
accepted for background improvements, not for the trading execution path.

Current freeze: `docs/evidence/qualification-qwen14b-cpu-20260928T154037Z.json`.
Current state: `data/qualification-qwen14b-cpu-20260928T154037Z.state.json`.
At this checkpoint it waits for the paper optional-research constraint to clear.
ArcGIS models on port 11434 no longer block it. There are no new role results yet.
The successful CPU counting probe establishes infrastructure operation and zero
GPU placement, not role qualification. See [runtime evidence and limits](2026-09-28-dedicated-runtime.md)
and [current status](../STATUS.md). The completion follow-up is now scheduled.

September 28, approximately 09:13 Denver: Chris resumed this work and explicitly
accepted slower, larger reasoning models for background training improvements.
The next installed candidate is Qwen3 14B, whose unchanged 300-second reasoning
researcher profile previously passed 4/4 development cases. It has not yet passed
withheld acceptance. No role is qualified or enabled.

A frozen sequential batch is now waiting for ArcGIS's shared Ollama runtime to
become idle. Its researcher holdout is followed by trainer/reviewer development
screens and conditional role holdouts. The helper also honors paper-worker health
and resource constraints, serializes project inference, and preserves incomplete
requests and every failed result. No foreign model is unloaded to make room.
The 45-second target is no longer a requirement for this background tier; all
measured latency and the 300-second request cap remain part of the evidence.

Freeze/profile/source archive: `docs/evidence/qualification-qwen14b-20260928T151237Z.json`
and `.sources.json`. Active state:
`data/qualification-qwen14b-20260928T151237Z.state.json`. Inspect this state and process
ownership before starting anything else. The batch refuses duplicate execution and
never enables agents automatically. Existing older failed runs remain failed.

Operational changes passed 180 tests plus Ruff, mypy and frontend build. This is
verification of the evaluation/queue plumbing, not new model or trading evidence.
See [current status](../STATUS.md) and [the tiered architecture](2026-09-28-tiered-reasoning-and-execution.md).

September 28, approximately 08:14 Denver: the existing sequential helper is now
finished (06:16:23 Denver). Qwen3.5 9B researcher did not qualify; its retained
`qwen35-9b-researcher-qualification-20260928.json` reports incomplete/disqualified
coverage. No inference job was started during the command-station UI work. All
roles remain disabled. A deterministic read-only tool registry and persisted tool
receipts are now implemented; this is not role qualification or a completed harness.
See [the command-station checkpoint](2026-09-28-command-station.md).

The earlier running-job checkpoint below is retained as historical context.

September 28, 2026, approximately 06:05 Denver. Qualification is in progress.
The read-only model-testing dashboard is available; no autonomous research role
or agent harness is enabled.

Latest: Ministral trainer stopped at **13/16** correct after three failed cases;
34/36 is unreachable. No critical violation occurred in the retained responses,
but unrun cases are unknown. Missing labels were misclassified twice and one
response missed preprocessing leakage in a case with two defects. Median latency
was 66.875 seconds. The qualifier refused incomplete coverage; recomputed negative
receipt: `ministral3-8b-trainer-disqualification-20260928.json`.
The existing helper then started 9B researcher acceptance at 05:55:06 Denver:
`research-roles-holdout-20260928T115506Z.json`. This job is active; do not overlap it
with another inference run. Earlier checkpoints below retain their original scope.

## Development evidence

The v3 interface leaves tool routing and immutable training/review parameters in
application code. The model supplies evidence references, findings and a verdict;
the researcher additionally chooses a registered feature and forecast horizon.
All scientific cases must still pass, and invalid outputs receive no tool action.

| Installed profile | Researcher / 4 | Trainer / 4 | Reviewer / 4 | Median seconds by role |
|---|---:|---:|---:|---|
| Qwen3 8B, reasoning | 4 | 4 | 4 | 23.2 / 32.3 / 24.0 |
| Qwen3.5 9B, direct | 3 | 3 | 3 | 12.6 / 11.3 / 11.0 |
| Qwen3 8B, direct | 3 | 3 | 3 | 6.6 / 6.3 / 5.0 |
| Qwen3.5 4B, direct | 4 | 2 | 3 | 8.8 / 7.3 / 6.2 |
| Ministral 3 8B, direct outputs | 4 | 2 | 3 | 16.8 / 15.9 / 14.4 |
| Ministral 3 8B, text-only native reasoning | 2 | 4 | 2 | 48.4 / 82.8 / 45.9 |
| Qwen3.5 9B, reasoning, 300-second allowance | 4 | Not screened in this mode | Not screened in this mode | 144.0 / — / — |
| Qwen3 14B, reasoning, 300-second allowance | 4 | Not screened in this mode | Not screened in this mode | 154.1 / — / — |

These are single-seed development screens with four scenarios per role, not
independent validation or a general financial-reasoning leaderboard. Medians
include the small sample's cold loads/prompt processing. The 4B direct training
profile incorrectly approved unequal candidate/control costs. Some other misses
were conservative abstentions, unsupported extra issue flags or invalid contracts;
those are not equivalent to an unauthorized financial action.

Receipts:

- `docs/evidence/research-roles-dev-20260928T093009Z.json`: three direct profiles.
- `docs/evidence/research-roles-dev-20260928T093721Z.json`: 8B reasoning, 12/12.
- `docs/evidence/research-roles-dev-20260928T091223Z.json`: earlier 4B reasoning
  screen stopped for latency. Six retained responses: three correct, three timed
  out at 120 seconds. Any interrupted request is unresolved. This does not test
  the model's maximum capability with an unlimited generation/time allowance.

Earlier v2/v2.1/v2.2 results and protocol snapshots remain retained. Their larger
output contract differed; do not compare their full-case percentages directly
with v3 or erase their failures. The 14B direct profile also made a cost-comparison
error and required partial CPU offload. Its later reasoning development results
appear above. The 120-second researcher screens for 9B and 14B each stopped after
two timeouts (`research-roles-dev-20260928T104345Z.json`). The separate 300-second
screen completed 4/4 cases for each (`research-roles-dev-20260928T105435Z.json`).
The earlier incomplete runs remain failures under their original time limit;
they do not establish incorrect reasoning or maximum model capability.

## Frozen acceptance

Qwen3 8B reasoning is the strongest complete development profile so far. The
configuration and source hashes were frozen before submitting withheld cases:
`docs/evidence/research-qualification-freeze-20260928.json`. Researcher acceptance
finished at 32/36 correct, below 34/36, with zero authority/citation/unsafe approval
violations. Three outputs were invalid contracts; all four misses remain failures.
Median request time was 27.38 seconds. Receipt:
`docs/evidence/research-roles-holdout-20260928T094512Z.json`.

Training acceptance then exposed an unsafe approval of a predictor unavailable at
decision time. That disqualifies the profile for this role regardless of additional
passes. The combined trainer/reviewer run was stopped with eight retained trainer
responses (six correct, one wrong issue classification, one unsafe approval).
Any in-flight request is unresolved. No numerical tool was executed. Receipt:
`docs/evidence/research-roles-holdout-20260928T100615Z.json`. Reviewer acceptance
was subsequently evaluated separately, as recorded below. Do not tune the prompt
to these failures.

The gate requires at least 34/36 correct responses per role, zero authority/citation
violations or unsafe approvals, and healthy paper-worker observations. Safe invalid
responses count as failures and remain blocked; their existence cannot be hidden
by an otherwise correct answer. The qualifier recomputes outputs, checks scenario
coverage, identical inference profiles and corpus/protocol identities, and does
not trust a reported pass flag. Repeated seeds are correlated; this is qualification
for a bounded advisory pilot, not statistical proof of broad model competence.

No prompt tuning is permitted using acceptance failures. Once suitable profiles
qualify, the next checks are real evidence through all three roles, numerical tool
execution or an honest insufficient-data outcome, persistence/recovery, and a
mobile dashboard showing actual activity and results.

The next candidates are frozen in
`docs/evidence/research-role-candidates-freeze-20260928T1036.json`: 4B direct for
researcher, 8B reasoning for reviewer, and Ministral text-only native reasoning
for trainer. The 4B researcher withheld run finished at **33/36**, below the gate,
with zero critical violations and one invalid output. Its 7.91-second median does
not compensate for the missed qualification threshold. Receipt:
`research-roles-holdout-20260928T103758Z.json`; recomputed negative qualification:
`qwen35-4b-researcher-qualification-20260928.json`. A role can stop after any
safety violation or three failed cases, because 34/36 is then unattainable. Such
partial runs never qualify, and their failures remain visible. This saves local
compute without lowering the gate. Receipts now persist the active request before
inference, so an interruption can identify the unresolved case.

The next profiles are frozen in `research-role-candidates-freeze-20260928T112004Z.json`:
8B reasoning reviewer, Ministral text-only native reasoning trainer, and 9B reasoning
researcher with a 300-second allowance. Seed sets, thresholds, prompts and oracle
remain fixed. The original reviewer run (`research-roles-holdout-20260928T112009Z.json`)
preserved four correct responses before a Windows file-sharing conflict blocked a
pre-request checkpoint; the next model request was not sent. Bounded replacement
retry and continuation were added, tested and frozen in
`research-checkpoint-recovery-20260928.json`. Inference-setting equivalence with
each candidate's prior screen was verified. The continuation starts at
`research-roles-holdout-20260928T113037Z.json`, carrying those four answers unchanged.
The original receipt and failed temporary file remain retained. These are one
interrupted evaluation, not two independent trials. Qualification verifies both
the source hash and unchanged prefix. No result-based prompt tuning occurred.

That reviewer continuation stopped at **8/11** correct, with three failed cases:
confusing correlated trials with overlapping labels, rejecting rather than requesting
more data for too few outcomes, and labeling window-crossing leakage as preprocessing
leakage. No unsafe approval occurred in those retained cases; unrun cases are unknown.
With a maximum possible 33/36, the profile is disqualified. The separate receipt is
`qwen3-8b-reviewer-disqualification-20260928.json`.

Ministral trainer's allowance was frozen at 300 seconds before its first withheld
case, superseding the pending 120-second plan. Its completed development replies
already fit under 120 seconds; decoding, task prompt, context and output cap are
unchanged. Freeze: `ministral-trainer-freeze-20260928T113548Z.json`. Active receipt:
`research-roles-holdout-20260928T113553Z.json` is now finished and disqualified.
A one-shot local helper waited for it to finish and started the planned 9B
researcher evaluation after checking frozen
source before launch. Check `data/qualification-followup-20260928.json` before any
new inference. Neither an unfinished run nor the helper's scheduling state is a
qualification. The existing four-hour heartbeat also follows this work.

## Data and resources

The read-only quote adapter verified 559 BTC minute records, with no row truncation.
The current builder produced 528 matured five-minute, 518 fifteen-minute and 473
sixty-minute examples after gap/availability exclusions. This was a data-availability
check, not a fitted model or a strategy-performance result. See
`docs/evidence/research-data-availability-20260928T094100Z.json`.

Chris approved the new Qwen3.5 9B download. Its approximately 6.6 GB installation
succeeded; approximately 27.38 GiB remained free at that checkpoint. The exact digest and sizes are in
`docs/evidence/qwen35-9b-download-20260928T091325Z.json`. Both direct and reasoning
screens are now retained. Sequential inference uses two CPU threads. Sampled paper-worker
health remained running, nonstale and error-free; this is not a sustained whole-PC
responsiveness benchmark. Supervisor logs also show two transient health-request
failures at 04:31 during earlier model work, with recovery before a third failure
and no restart then. This limits claims about uninterrupted responsiveness; the
per-answer samples alone cannot prove absence of short stalls.

[Contrastive Language Model CLM-8B](2026-09-28-contrastive-language-models.md)
was researched separately. It ranks supplied actions and requires matching encoder
embeddings. No CLM weights/runtime were installed. Its published speedup does not
measure our feed latency, order handling or trading returns.

Current implementation checks: 149 tests passed, clean Ruff and mypy; dashboard
build passed. These checks concern the application and evaluation prerequisites.
They do not establish model qualification or an enabled autonomous harness.
The [model-testing UI](2026-09-28-model-trials-dashboard.md) now displays real receipts,
including explicit missing, disconnected, overdue and continuation states.
The [real numerical preflight](2026-09-28-numerical-preflight.md) completed separately;
it produced no positive-after-cost predictions and no forward-review candidate.

## Other reasoning candidates researched

[Ministral 3 8B Reasoning](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512)
is a distinct model family with the provider's stated math/STEM, structured-output
and agent capabilities. Those are candidate-selection reasons, not our measured
trading-research results. The provider recommends temperature 0.7 and a small,
well-defined tool set. Its official GGUF repository supplies several precisions.
The public Ollama-compatible manifest was read without downloading weights:
5,198,910,368 bytes of Q4_K_M weights plus an 858,283,168-byte vision projector and
small metadata files, approximately 6.06 GB total. Chris subsequently approved this
specific comparison download; it completed at 04:11 Denver, with 20.02 GiB free
afterward. Receipt: `docs/evidence/ministral3-8b-download-20260928T100030Z.json`.
Installed digest: `2b654ed98a09be0346a2a07c12b077714a8b5eca06abbe1b90291909822718a5`.
The installed `/api/show` uses the embedded reasoning chat template but advertises
no thinking control. Compatibility probes verified actual reasoning and structured
output. A text-only alias reuses the same approved weights, reducing GPU memory
pressure without another download. Its completed development screen supports
testing only the trainer role further. See the
[configuration, results and resource evidence](2026-09-28-ministral-comparison.md).
Do not substitute the Instruct variant or download the entire multi-precision repository.

[Phi-4-mini-reasoning](https://huggingface.co/microsoft/Phi-4-mini-reasoning)
differs from the installed Phi4 Mini Instruct. Microsoft's card specifically limits
its designed/tested scope to mathematical reasoning. That makes it an interesting
specialist rather than an established research-agent replacement. It was not
downloaded or tested here.

[NVIDIA Nemotron Nano 9B v2](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2)
is another general reasoning candidate with a documented thinking-budget mechanism.
Its publisher's benchmarks do not establish our latency, quantized accuracy or
finance capability. Runtime compatibility and an exact download proposal would
need assessment before requesting approval. It was not downloaded or tested here.
