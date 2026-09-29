# Source status — September 29, 2026

The reference UI is implemented on the audited stack. The full local PostgreSQL
suite passed again: 382 tests, no skips, 78.53 seconds; lint, strict types and the
production dashboard build passed. Actual synthetic browser workflows and native
screenshots are retained in `reviews/reference-ui/`. Unknown confidence and missing
history remain explicit; the interface grants no new financial authority.

Chris authorized merging all outstanding Q-Trades PRs and relaunching the existing
native paper application after checks. Exact-head hosted, final-main, merge and
private installation/preservation evidence must be observed separately. Future
prospective market acceptance remains pending; the live decision is not ready.

## Audit source checkpoint before UI

CP4–CP9 and the CP0–CP9 efficiency audit are complete as stacked draft PRs #7–#13.
The audit's final implementation is 06ca527: local PostgreSQL suite 382 passed
without skips, lint/types/dashboard build passed, seven synthetic normal-browser
checks passed, and hosted run 36642583198 passed (158 tests, 32 database skips).
All six final capacity cases and the five-minute twenty-account busy soak passed.
Retained measurements and limits: `reviews/cp0-cp9-efficiency-audit/README.md`.

Next authorized source work is the UI inspired by `C:\Projects\Q-Trades UI Inspo`.
These drafts have not been merged or installed. The original trial, manual updater
and advisory/GIS runtimes were not changed. This source work does not refresh the
historical operational snapshot below. Subsequent real-market evidence remains
pending; CP9's live-readiness packet concludes not ready.

---

# Historical operational status — September 28, 2026

Latest operational check: **16:25 Denver**. The paper worker remains running, fresh,
unpaused and reconciled (read-only audit revision 161826). Primary equity is still
$97.5097533402, with 19 closed trades. Its last closure was **12:55:22 Denver**.
Since that closure, 420 recorded primary entry evaluations comprise 404 strategy
condition rejections, ten symbol cooldowns and six stale-metadata rejections.
These evaluations are correlated observations, not independent opportunities.
The **13:05** review retained breakout-v1; the next review is approximately **17:05**.
No risk pause, outstanding primary position, replenishment or strategy promotion
is present. Live feed reconnections and explicit REST fallback continue.

Model testing remains stopped, with no queue/evaluator process running. A bounded
12-sample read-only database probe with no trading inference resident observed
maximum read/recent/reconcile/storage-query times of 13.0/18.0/15.9/26.2 ms.
It did not reproduce the earlier engine cooldown triggers and cannot identify their
cause or establish behavior under inference load. Per-operation engine timing at
the actual trigger is still needed before a new frozen qualification continuation.
No worker was restarted and no model request, gate change or financial write was
performed for this check. Evidence: `docs/evidence/paper-status-20260928T2224-audit.json`.

The last qualification checkpoint was approximately **13:23 Denver**. The restarted batch stopped
at **13:07:35** after exhausting its **1,800-second cumulative resource-wait allowance**.
Trainer and reviewer each passed 4/4 development checks. Trainer holdout completed
**8/36 answers, all passing**, with 28 untested; reviewer holdout never began.
The independent qualifier rejects both as incomplete, so **no role is qualified**.
All completed answers, the original imported prefix, model/profile, frozen files and
source archive verify unchanged. Queue/evaluator processes have exited; no request
remains in flight. The 15-minute completion watcher is **paused**; the four-hour
paper/research follow-up remains **active** and owns the next investigation.
See the [terminal review and next step](research/2026-09-28-1323-model-result.md).
Evidence: `docs/evidence/qualification-qwen14b-resume-20260928T173007Z.terminal.json`
and `docs/evidence/model-watch-20260928T1916-processes.json`.
Earlier wait, recovery and failure snapshots remain unchanged.
See the [resource recovery implementation](research/2026-09-28-resource-resume.md).

The preceding batch stopped at 10:47 after one passing trainer development check
in 297.172 seconds. Its original receipt, resource-stop status and rationale caveats
remain unchanged. That earlier batch covered trainer 1/4 and reviewer 0/4; neither reached
holdout. See the [prior terminal result](research/2026-09-28-1100-model-result.md).

Both project scheduled
tasks are Running through a new windowless Python host. Windows integration tests
verified that host and supervisor have no attached console, and preserve child
logs and exit codes. The existing paper worker (55988) and ArcGIS runtime (11844)
were preserved. Earlier supervisors exited again at 10:21 with `0xC000013A`; the
source of that interruption is unknown. Window isolation is verified, but sustained
unattended reliability is not yet established. The
[heartbeat audit](research/2026-09-28-0954-heartbeat.md) retains all failures.

At the latest snapshot, primary equity was **$97.5097533402**, with 19 closed trades,
$1.8271306598 fees and lifetime net P&L **-$2.4902466598**. Its first $100 attempt is
still open; no replenishment or completed success/failure attempt occurred. The
13:05 review retained breakout-v1 with insufficient forward evidence and no passing
challenger. WebSocket books are arriving, but delayed messages and depth coverage
gaps cause reconnects/REST fallback; this is not uninterrupted live-feed evidence.
Freshness checks, strategy settings, risk limits and funding rules are unchanged.

The original two-processor model batch stopped at 09:53:43 with a **600.015-second
incomplete first development response**, then hit the paper resource guard. All
three roles remain unqualified. Its terminal receipt, source archive and failure
are retained; no prior score was changed.

The separate elastic CPU profile is now operational: six inference threads, all
12 logical processors eligible, Windows IDLE priority and zero GPU use. A counting
probe completed in 71.329 seconds at 2.799 generated tokens/second with verified
process identities/priority/affinity. This does not prove simultaneous ArcGIS
latency or role competence. GPU handoff remains unimplemented.

The first elastic batch (`qualification-qwen14b-elastic-20260928T161443Z`) stopped
at 10:23. Its first researcher answer completed in 442.235 seconds but **failed the
research contract** by inventing missing data for an otherwise valid feature. The
supervisor's stale heartbeat also failed placement verification. The answer,
negative result, original sources and terminal receipt remain; it will not be
retried to obtain a passing answer. Trainer and reviewer were not tested there.

**Terminal continuation:** `qualification-qwen14b-resume-20260928T173007Z`.
State: `data/qualification-qwen14b-resume-20260928T173007Z.state.json` is `needs_review`.
Original queue launcher 28312 / Pythonw 19768 and holdout evaluator launcher 34684 /
Pythonw 24000 are no longer present. Development receipt:
`docs/evidence/research-roles-dev-20260928T173102Z.json`; trainer/reviewer median
times were 269.1485 / 160.461 seconds. The seven new answers completed without
repeating the imported original trainer case. Holdout receipt:
`docs/evidence/research-roles-holdout-20260928T175618Z.json`; eight answers took
233.688-354.359 seconds, median 323.0855 seconds. The latest correctly rejects
selecting 80 variants using the final test block. Only eight distinct scenarios under
seed 92811 ran; the remaining 28 responses and all 36 reviewer holdouts are untested.

Five wait episodes recovered. The sixth exhausted the allowance before
`holdout-trainer-split_overlap` was dispatched, with 1,800.047 measured wait seconds.
No response was in flight or lost at that stop. All eight development and eight
holdout answers independently pass contract, citation, expected-decision, CPU-placement
and paper-health checks. Their partial coverage cannot qualify a role. Retained
rationale caveats concern the original trainer's label-maturity terminology and both
roles' loose attribution of separate leakage controls to purging; scores remain unchanged.

Both project tasks and original service processes remain running. The trading model
is unloaded; its server remains IDLE with affinity 4095 and the six-thread CPU profile.
ArcGIS runtime 11844 was preserved and has its own model activity; request latency
remains unmeasured. At 13:23 paper was fresh, error-free, unconstrained and balanced
(engine p95 63 ms, commit p95 47 ms). Later resource recovery does not erase the
terminal stop or reset its waiting allowance. No service was restarted.

Next: investigate repeated slow paper-engine work before any separately frozen
continuation. Aggregate p95 measurements cannot identify the triggering samples.
Preserve all eight holdout answers, exhausted wait history, earlier failed researcher
answer and consumed numerical test boundary. No new model was activated or qualified.

Resource waiting/recovery is implemented under separately frozen `resource-yield-v1`:
up to 1,800 cumulative wait seconds per evaluation stage, with 30 seconds of recovered
resources before dispatch. Wait state and every completed response are persisted.
Other worker-health or placement failures still stop the run. Only an explicitly
requested, finished resource-gate stop with no in-flight or disqualified role can be
continued into a new receipt. The original stop state and answers are never edited.
The prior failed researcher answer remains excluded. Do not change active frozen
files or allocation. Synthetic recovery tests passed, and a real wait/recovery cycle
is now persisted in this continuation. The gate acts between requests; this does not
prove cancellation of an in-flight request or ArcGIS response latency.

Inspect **both python.exe and pythonw.exe** plus state before stopping the runtime.
After preserving this terminal batch, the stop helper was extended to cover both
names. Disposable tests verify that it refuses active jobs before any server lookup
or stop. The old archived helper remains unchanged. See
[resource policy](research/2026-09-28-resource-priority.md).

Verification: **220 tests passed**, including 52 focused research/recovery checks.
Ruff, mypy (34 files) and web build passed. An end-to-end simulated restart proved
only unfinished cases were dispatched, retaining the original receipt byte-for-byte.
Prior failures remain recorded; the existing Starlette warning remains.
The numerical consumed-test boundary remains `1790595239.9180105`.

At approximately 09:50 Denver, the dedicated CPU qualification batch is **evaluating**.
The first researcher development request began at 09:43:43; no response had completed
at this checkpoint. Model placement reports zero GPU bytes; server and model worker
are verified BelowNormal with the frozen two-processor affinity. No role is qualified.
Chris's subsequent resource direction is elastic: research may use spare capacity
but must yield to ArcGIS demand. That automatic policy is not enabled yet; preserve
the active test allocation and follow the [resource-priority implementation record](research/2026-09-28-resource-priority.md)
after it terminates. Separate processes alone do not provide GPU preemption.

At approximately 09:42 Denver, Chris's separately authorized **dedicated model
runtime is running** at `127.0.0.1:11435`, using CPU only, two logical processors,
below-normal worker priority and installed weights. ArcGIS retains its existing
GPU-capable server at 11434. Both services are loopback-only; no shared settings,
weights, account state or paper process were replaced. The separate task is
`TradingResearch-Models-20260928`; status is `data/research-runtime.json`. Inspect
recorded process identities before taking any action. See the
[runtime operation and measurement record](research/2026-09-28-dedicated-runtime.md).

The original waiting batch was superseded **before any inference request** and
preserved. The current CPU-profile freeze is
`docs/evidence/qualification-qwen14b-cpu-20260928T154037Z.json`; active state is
`data/qualification-qwen14b-cpu-20260928T154037Z.state.json`. Launcher PID 49672,
Python PID 44656 at this checkpoint. It first screens all three roles with a
predeclared 600-second CPU request cap, then conditionally runs each role's holdout.
Prompts, corpus, decoding and correctness/authority gates are unchanged. It currently
waits on the paper worker's optional-research constraint, not the ArcGIS runtime.
Do not start another trading inference job or rerun either batch.

The successful infrastructure probe measured 1.583 generated tokens/second and
zero GPU bytes; this was a counting prompt, not role or trading validation. Two
earlier attempts stopped before inference because the paper resource guard was
active. The first startup failure and all probe receipts are retained. Subsequent
worker-priority enforcement corrects Ollama's explicit above-normal child priority.
Runtime stop/start preserved ArcGIS PID 11844 and paper PID 55988. The new runtime
server is PID 43420, supervisor 47256, at this checkpoint. No model has qualified.

Verification: **182 tests passed**, 27 focused research tests passed after the
runtime-version checks, Ruff/mypy and web build passed. Dedicated start, stop,
restart, loopback ownership and unchanged installed model digest were checked.
The existing Starlette/httpx warning remains. The paper worker is running, fresh
and error-free, but its optional-research constraint has been active intermittently;
do not remove that guard to force testing. Its older scheduled supervisor is again
Ready while the same Python worker runs; the previously documented exit cause
remains unresolved and was not changed in this runtime work.

A separate temporary heartbeat, `report-dedicated-model-test-results`, now checks
completion every 15 minutes and reports verified results or a terminal blocker,
then pauses itself. The four-hour paper experiment automation remains active.

At approximately 09:13 Denver, Chris resumed agent-harness qualification and
confirmed a tiered architecture: slow, larger models for research/training
improvements; eventually validated quantitative scores and deterministic execution
for fast trading. Small LLM helpers remain optional. The prior 45-second research
latency target is no longer a selection requirement for the slow background tier.
The next comparison keeps its already screened 300-second request cap and unchanged
correctness/authority gates. See the [tiered design](research/2026-09-28-tiered-reasoning-and-execution.md).

The installed **Qwen3 14B reasoning batch is queued, not yet inferring** at this
checkpoint. ArcGIS Pro was observed connected to the shared Ollama runtime, with
Qwen3 8B resident. The helper waits for an empty runtime for 30 seconds and a healthy,
unconstrained paper worker; it does not unload the ArcGIS model. It then runs the
14B researcher holdout, trainer/reviewer development screens, and holdout checks only
for roles passing 4/4 development cases. One role needs 34/36 correct with no critical
violations. All outputs and independently recomputed qualifications are retained;
there is no automatic harness activation. No role is qualified yet.

Active helper: `scripts/run_qualification_queue.py`, launcher PID 12468, Python PID
29524 at this checkpoint. Verify ownership and current state before touching it.
Freeze: `docs/evidence/qualification-qwen14b-20260928T151237Z.json`.
State: `data/qualification-qwen14b-20260928T151237Z.state.json`; associated `.log`
files and `.pid.json` share that prefix. Do not rerun this frozen batch or overlap
it with another evaluation. It has a cumulative six-hour idle-wait allowance and a
bounded per-stage evaluation budget. Source drift, interruption or exhausted idle
waiting leaves a visible `needs_review` state; preserve any receipt and unresolved
request before using the existing verified-prefix continuation mechanism.

Evaluator changes add a project inference lock, honor `research_constrained`, avoid
starting a request while a different model is resident, and retain completed answers
when a health request fails. The project lock cannot control unrelated applications
starting new Ollama requests. Their future activity can still compete with a request
already in progress. No old prompt, oracle, score or receipt was rewritten.

Verification: **180 tests passed**, Ruff and mypy passed, frontend build passed.
One existing Starlette/httpx deprecation warning remains. Paper worker was running,
fresh and error-free, approximately 1.77% average machine CPU, engine p95 79 ms,
commit p95 47 ms, and 53.82 GiB free disk at this checkpoint. No paper restart,
account change, weight download or paid call was needed. The consumed numerical
test boundary remains `1790595239.9180105` for any future research journal import.

At approximately 08:29 Denver, Chris's follow-up added **Strategies & learning**
inside the command station. It shows the actual frozen 10-minute/2x, 7-minute/1.5x
and 15-minute/2.5x breakout variants, their separate BTC/ETH net outcomes, the
active primary rule, and selected-market trend/breakout/volume/ATR checks. Rule
parameters come from the engine's existing variant bank. Inspecting a comparison
does not change the trading rule. Stale/missing signals become Unknown.

The UI also explains initial 1.5x ATR protection, trailing activation after a 1R
price gain, a 1x current ATR trail that never loosens, the ten-minute progress exit
and 45-minute maximum hold. Trail activation does not establish net profitability
after costs. Sizing and execution assumptions are available on demand. Current
learning is bounded selection among frozen variants; the latest recorded review
retained baseline with insufficient forward evidence. No entry, exit, cost, risk,
learning-gate or financial rule changed.

All **170 tests passed**, Ruff and mypy passed, and the frontend built successfully.
Desktop and 360-pixel phone strategy views were inspected, including switching
which comparison is displayed while the API retained `breakout-v1` as primary.
The added read-only evidence is about 3 KB per ten-second detail refresh. After the
owned reload, all six spot account fields, options accounts and six tool receipts
were preserved. The full paper report reconciled at revision 90717. The task and
worker remained running at this checkpoint. Receipts: `strategy-view-*-20260928.json`.

At approximately 08:14 Denver, the local **Market command station** is implemented
and browser-verified on desktop and 430/360-pixel phone layouts. It combines a
searchable market screen, live bid/ask/spread, real closed-minute candles/volume,
visible depth, observed exchange prints and recorded primary decisions/activity.
The 30m/1h/2h controls select retained candles; no synthetic data is supplied for
unsubscribed markets. Metadata stays behind collapsed diagnostics, including the
older feed/storage/performance panel. No charting dependency was added.

Four deterministic read-only tools now share that evidence: market inspection,
modeled cost hurdle, recorded-decision explanation and retained-outcome review.
The UI invokes them explicitly and can reopen persisted results. An isolated SQLite
journal retains completed, failed and interrupted runs, result hashes and versions;
capacity blocks new optional work instead of deleting history. These tools grant
no account authority and do not activate the LLM harness. No model has qualified.
The existing Qwen3.5 9B helper finished at 06:16 Denver with a negative qualification
receipt; no inference process or weight download was started during UI work.

Verification: **168 tests passed**, Ruff clean, strict mypy clean (33 source files),
TypeScript/Vite build passed. One existing Starlette/httpx deprecation warning remains.
Actual browser checks exercised BTC/ETH switching, no-match and liquidity filters,
120-candle range selection, all four tools, a failed AAVE cost request with no live
quote, saved receipts, collapsed diagnostics and responsive layout. No browser
warnings/errors appeared in the final check. See the
[command-station checkpoint](research/2026-09-28-command-station.md).

The final backend reload used only the verified project worker and existing task.
All six spot accounts preserved cash, funding, fees, realized results, closed trades,
positions, pending orders, attempts and replenishments; options accounts and three
existing tool receipts were unchanged. Journal revision 89006 reconciled with zero
imbalanced events or projection errors. Primary equity was **$98.6630401795**, ten
closed trades, attempt 1 open and zero replenishments. A natural BTC loss before this
reload explains the change from the earlier nine-trade checkpoint; no history was reset.

The scheduled supervisor had exited again at 07:56:44 (Windows result 3221225786),
while its Python worker continued running. The cause remains unexplained. Ownership
was verified before reloading through the same task at 08:08:23; supervisor and paper
worker subsequently remained running through the browser checks. This is not proof
that the earlier supervisor-exit condition is repaired. Preserve that uncertainty.

Prior checkpoints follow, with their original evidence and limitations.

At approximately 07:34–07:36 Denver, the dashboard's single **Live bid & ask** panel
was verified against the running paper feed. It shows actual bid/ask prices, actual
WebSocket or REST-fallback source, receipt age, exchange timestamps where available,
and explicit stale/unavailable states. Browser refresh is approximately one second;
the worker's 100 ms / 1 s subscriptions run independently. The confusing 15-second
USD/USDT price table and its navigation entry were removed at Chris's request. Its
separate bounded REST diagnostic capture still runs and can be paused under Operations.

The new `/api/paper/quotes` reads at most eight existing books without venue requests,
database reads, captures or financial-state writes. Tests cover decimal prices,
sequence regression, clock invalidation, expiry, stopped workers, REST timestamps,
bounded output and GET-only/no-store API behavior. All 159 tests passed; Ruff,
strict mypy (31 files), and the TypeScript/Vite build passed. An initial lint check
found three overlong test lines; those were corrected before the clean full check.
The actual desktop browser showed changing prices and timestamps, fresh and expired
quotes, and no old price table or horizontal document overflow.

The old supervisor had exited while its paper worker remained alive; the first
restart ownership check correctly stopped without changing any process. After
verifying the worker path, parent relationship, loopback listener and existing task
action, the worker was reloaded through `TradingResearch-Paper-20260927`. The task
is now Running; its new supervisor started at 07:33:35 and worker launcher 7204 at
07:33:39. No model evaluation was active. Journal revision 84902 reconciled, all six
spot accounts preserved cash, funding, fees, realized results, closed trades,
positions, pending orders, attempts and replenishments, and options account state
was unchanged. Primary remained $98.8371108497 with nine closed trades, no positions
or replenishments; this UI change does not establish trading success.

The yellow research-reduction notice was still present after reload. With 48.88 GiB
free and no capture error, the current condition follows the five-minute engine-work
cooldown, not the disk threshold. Recent engine work p95 was 62 ms; the specific
outlier that triggered the cooldown is not exposed, so its cause remains unverified.
No resource or risk limit was relaxed. Receipts: `docs/evidence/live-quotes-*-20260928.json`.

At approximately 07:10 Denver, `C:\Users\chris.t0\Desktop\Trading Research.exe`
was built and installed locally (10,240 bytes). It opens the local dashboard and
can request the existing, identity-checked startup task when unavailable. Source
and build instructions are in the README. PowerShell syntax, warning-free C#
compilation, read-only executable check and normal browser-launch path passed;
the paper launcher PID remained 21356. Cold-start recovery was not exercised by
stopping the running experiment. No engine/frontend code or model configuration
changed, and the earlier Python/frontend test results were not rerun for this launcher.

**WebSocket restored at approximately 07:04–07:05 Denver.** After Chris allowed Japan
on SonicWall, verified TLS and a live depth message succeeded. The running app
automatically switched BTC/ETH to fresh, sequence-validated WebSocket books, with
advancing timestamps/counters across three observations. No restart was needed.
Historical gaps and losses remain retained; journal revision 81168 balanced.
Primary equity was $98.8371108497, nine closed trades, no positions/replenishments.
Two optional-symbol REST warnings remained; this is not proof of every market's
health or sustained low latency. See the [resolution and receipts](research/2026-09-28-websocket-sonicwall-fix.md).

The 05:53 heartbeat verified a running local service/task and a balanced journal.
Primary equity was $99.3224263613, with five closed trades, zero wins, no positions
or replenishments and attempt 1 open. Three new primary ETH losses totaled
$0.436953622 after costs since the prior heartbeat. The 05:05 review retained
`breakout-v1`; no promotion met the evidence gates. Next review: 09:05 Denver.
Two retained approximately 48-second gaps align with the prior dashboard restarts;
REST fallback remains usable while WebSocket has received no books/trades.
Free disk was 19.8 GiB. See the [heartbeat audit](research/2026-09-28-0553-heartbeat.md).

At 05:55, Ministral trainer acceptance stopped at 13/16 correct, with three failures
and zero observed critical violations. It cannot reach 34/36 and is disqualified;
the qualifier refused incomplete coverage. The existing sequential helper then
started Qwen3.5 9B researcher acceptance (`research-roles-holdout-20260928T115506Z.json`).
Do not start another inference job while it is active. No model is qualified and
the advisory harness remains disabled. Chris's question about C#/Visual Studio
wrappers is addressed in [wrapper options](research/2026-09-28-model-wrapper-options.md);
no runtime rewrite, prompt change or extra model download was performed.

At approximately 05:46 Denver, Qwen3 8B reviewer acceptance stopped with 8/11 correct,
three failed cases and no observed unsafe approvals; 34/36 is now unattainable.
Its original receipt, continuation and failures remain retained. Ministral text-only
reasoning trainer acceptance is running with a predeclared 300-second allowance.
Nine responses were retained at this checkpoint, eight correct and one safe but
incorrect rejection/classification of unavailable labels. No role is qualified.

A hidden, project-owned one-shot helper waits for that run to finish, then evaluates
Qwen3.5 9B researcher sequentially and writes its qualification result. Its source
is `data/qualification-followup-20260928.py`, current state is
`data/qualification-followup-20260928.json`, and launcher PID is recorded in
`data/qualification-followup.pid`. Verify process identity before interacting; never
start a competing inference job. It stops for changed frozen source or a stalled
dependency and grants no agent/trading permissions. It is not a recurring service.
The existing four-hour heartbeat remains ACTIVE and now includes continued model
qualification and the previously authorized conditional advisory-harness work.

The first real numerical preflight completed on 674 BTC quote minutes: 431 training
and 191 test examples after exclusions/purging. Forecast MSE was 3.308% lower than
the fixed baseline, but zero predictions cleared costs, so the candidate is ineligible
for forward review. This is neither a trading return nor an independent market test.
The consumed test end, 1790595239.9180105, must seed any future research journal;
reusing it correctly returned insufficient data. See the
[numerical preflight](research/2026-09-28-numerical-preflight.md).
Paper health was running, nonstale and error-free; actual market sources remain
REST fallback or unavailable while the Binance.US WebSocket times out.

At approximately 05:30 Denver, both approved comparison downloads are installed.
Qwen3.5 4B direct researcher failed withheld acceptance at 33/36 (34 required).
Qwen3.5 9B and Qwen3 14B reasoning each passed four researcher development cases
with a 300-second request allowance; medians were 144.0 and 154.1 seconds. These
are background-research candidates, not qualified agents or trading latency results.
The Qwen3 8B reviewer withheld run is continuing from four preserved responses.
A Windows receipt-replacement conflict was repaired with bounded retry and verified
continuation into a new receipt; no prompt, oracle or inference settings changed.
Ministral trainer and 9B researcher acceptance remain pending. No agent is enabled.

The local dashboard now has a read-only **Model trials** view showing actual requests,
scores, timing, final explanations, input evidence, failures and interrupted runs.
Desktop, 430-CSS-pixel layout, expansion, disconnected snapshot and overdue states
were checked in the browser. This is evaluation visibility, not a working agent harness.
Checks: 149 tests passed; Ruff, mypy and dashboard build passed. The owned service
was restarted to load the view; journal revision 69299 reconciled, funding/attempts
and replenishment histories were unchanged. Primary equity was $99.3224263613,
five closed trades, no positions, no replenishments and attempt 1 still open.
Approximately 20.58 GiB free was observed at 05:33; no user cleanup was performed.
WebSocket remains blocked by the firewall; public REST fallback continues.
See [model qualification](research/2026-09-28-local-model-qualification.md) and
[model trial dashboard](research/2026-09-28-model-trials-dashboard.md).

At approximately 04:38 Denver, Ministral 3 8B Reasoning is installed and compared.
Its text-only configuration uses the same downloaded weights and fits in GPU memory.
With native reasoning it passed 2/4 researcher, 4/4 trainer and 2/4 reviewer development
cases. Only trainer proceeds to withheld testing; its median 82.84-second latency is
for background research, not trading. The next frozen candidate evaluations are
4B direct researcher, 8B reasoning reviewer and Ministral trainer. The 4B withheld
run has started. No role is qualified and no harness or agent UI is enabled.
Current checks: 140 tests passed, clean lint/type checks; dashboard build passed
before these backend evaluation changes. See the
[Ministral comparison](research/2026-09-28-ministral-comparison.md) and
[qualification checkpoint](research/2026-09-28-local-model-qualification.md).

At approximately 04:12 Denver, Qwen3 8B reasoning failed withheld researcher
acceptance at 32/36 correct (34 required), despite 12/12 earlier development passes.
Training acceptance then exposed an unsafe approval of an unavailable predictor;
that role is disqualified and the partial run/failure is preserved. Reviewer
acceptance has not begun. Chris approved Ministral 3 8B Reasoning (about 6.06 GB),
which is installed for comparison, leaving 20.02 GiB free. No model is qualified and no agent harness
was enabled at that checkpoint. The numerical
data adapter confirms 559 BTC quote minutes / 528 usable five-minute examples,
without financial writes. Current code checks: 139 tests passed, lint/type checks
and dashboard build clean. See the [qualification checkpoint](research/2026-09-28-local-model-qualification.md).

Earlier local development screens exposed substantive
method errors as well as mechanical response-contract failures; no model is
qualified and no autonomous LLM harness is enabled. All withheld acceptance cases
remained unused at that earlier checkpoint. The new protocol, evaluator, qualification gate
and fixed numerical experiment are local development prerequisites. Chris approved
Qwen3.5 9B; its 6.6 GB download completed, leaving about 27.38 GiB free. Installed
4B/8B reasoning profiles are being screened before the new candidate. The running
paper worker remains healthy. See the [qualification plan](research/2026-09-28-agent-qualification-plan.md)
and [CLM-8B assessment](research/2026-09-28-contrastive-language-models.md).

WebSocket cause identified at approximately 02:05-02:14 Denver: SonicWall's
**Gateway GEO-IP Filter Alert** blocks the Binance.US stream destination as Japan.
A scoped packet capture and an explicit block response corroborate the finding.
The stream is not restored. Chris will address the firewall at the office; the
required path is outbound TCP 9443 to `stream.binance.us`, with a scoped Geo-IP
exception appropriate to the existing firewall mode. No firewall or runtime setting
was changed. REST fallback and automatic retries continue. The service remained
healthy and the journal balanced at revision 49619, with primary equity unchanged.
See the [evidence, correction scope and verification steps](research/2026-09-28-websocket-sonicwall-fix.md).
This supersedes the unknown-cause diagnosis in the earlier dated checkpoints below.

The 01:36-01:40 Denver heartbeat verified the running service/task and independently
balanced journal. Primary remains $99.7593799833 with two closed trades; responsive
shadow added one BTC ATR-stop loss of $0.1269498208 including fees. All six accounts
are flat, separately funded, unreplenished and in their first unresolved attempt.
The second review at 01:05 retained breakout-v1 for insufficient evidence; next
review is 05:05 Denver. REST works; a fresh probe still finds Binance.US stream TCP
timeouts. Optional research was constrained about 15.3 minutes in four hours;
PostgreSQL size grew about 18.4 MB over that dated interval. No runtime changes or
restart were warranted. See the [heartbeat review and receipts](research/2026-09-28-0136-heartbeat.md).

WebSocket investigation at approximately 21:59 Denver reproduced TCP timeouts
before TLS/HTTP upgrade using both Python and .NET, across four current DNS
addresses and ports 9443/443. Binance.US REST and a Kraken WebSocket control work.
The stream remains unresolved; no supported endpoint correction was identified.
A bounded, read-only diagnostic script and receipts are available. Streaming
component tests: 17 passed; diagnostic Ruff/mypy clean. No runtime or network
configuration was changed. See the [diagnosis and next checks](research/2026-09-27-websocket-diagnosis.md).

Heartbeat at approximately 21:35-21:39 Denver verified the local service, owned
scheduled task and durable paper report. Independent journal reconciliation passed;
primary remained $99.7593799833 with two closed trades, no new fills, and no
replenishments. The 21:05 review retained breakout-v1; next review is 01:05 Denver.
REST fallback works; streaming remains unavailable and both direct TCP probes timed
out. No strategy, risk, funding or process changes were made. See the
[heartbeat assessment and receipts](research/2026-09-27-2135-heartbeat.md).

Local model comparison completed around 21:31 Denver: task-specific Python probes
tested installed Qwen 2B, 4B and 8B profiles. See the
[results and limitations](research/2026-09-27-local-model-results.md) and
[proposed agent harness](research/2026-09-27-agent-harness.md). Results support small
helpers plus separately evaluated reasoning roles; they do not establish reliable
autonomous research or a trading advantage. No research agents were enabled in the
trading worker. Benchmarks used local inference only; no downloads or paid calls.

Latest development direction: focus on crypto spot, with trainable prediction models
and LLM-assisted hypothesis research as the target. Stocks/options expansion is deferred.
See the [crypto learning plan](research/2026-09-27-crypto-learning-plan.md). This is a
direction and implementation specification; no model training or LLM service was enabled
by this audit. Existing workers and account histories were left intact.

Follow-up at 21:09 Denver: the first spot review had completed automatically around
21:05 and retained breakout-v1 for insufficient forward evidence/no passing challenger.
Primary equity remained $99.7593799833 with two closed trades and no replenishment.
The [follow-up receipt](evidence/crypto-focus-audit-2026-09-27.json) also records current
venue limits and the difference between the simulator's 0.10% per-side fee assumption
and the published 0.02% taker rate on most pairs. No fee model was changed or old
trade regraded. The earlier 20:57 observations below remain a dated checkpoint.

The separate free-data options account was activated at 19:52 Denver. It starts with
its own $100 and studies chronological AAPL historical end-of-day quotes; this is
not a live options feed. No broker account, key, subscription or LLM call is required.
Its first four-hour review is due around 23:52 Denver. See the options checkpoint below.

Subsequent research: Chris accepts opening a free account for data. Public documents
a free API with live options quotes; unfunded-account entitlement remains unverified,
and its inactivity-fee condition needs attention. TradingView is not an appropriate
automated data backend under its published terms. See the
[comparison and proposed validation](research/2026-09-27-live-options-data.md).
No broker feed has been connected or runtime changed by this research.

Learning audit at 20:57 Denver: spot primary remained $99.7593799833 after two closed
trades; options reached 59 historical sessions / 5,072 contract observations with zero
trades and the daily request budget exhausted. Neither first scheduled review was due
yet. Seven focused learning/failure tests passed. See the
[assessment and proposed next work](research/2026-09-27-learning-assessment.md);
it distinguishes programmed strategy selection from model training and causal diagnosis.

The original Tier 3 $100 experiment continues. At approximately 19:54 Denver, the
primary had $99.7593799833000000000 cash/equity, two naturally completed trades,
zero winning trades, $100 total fake funding and no replenishments. It had no open
position or pending order. One attempt remains unresolved; majority success is not
established. Its first four-hour review is due around 21:05 Denver. Query live status
for later results; this file is a checkpoint, not the account authority.

## Implemented and enabled

- Primary $100 account and three separate frozen strategy shadows, originally BTC/ETH.
- Two separately funded $100 comparison accounts: BTC/ETH control and screened wider
  USD universe, using the same breakout strategy and costs. Funds are never pooled.
- Closed-bar study, delayed capped fills, fees, reservations, fixed risk limits,
  PostgreSQL events/journal and independent reconciliation of every inventory asset.
- Four-hour forward-evidence reviews, bounded strategy selection and explicit
  insufficient-evidence outcomes. Below-$5 failure review precedes replenishment.
- Minute-by-minute liquidity screening, candidate promotion/demotion, fast
  held-position feeds, candle warmup and adaptive research throttling.
- Public WebSocket depth/trades/klines adapter with sequence reconstruction, clock
  checks, stale rejection and resync. Actual stream connectivity has not succeeded
  here; real public REST fallback is active and visibly labeled.
- Dashboard actual transport/age, capture size/rate, database size, free disk,
  application CPU and engine timing; actual mobile layout inspected.
- Dedicated loopback PostgreSQL, current-user sign-in task and hidden supervisor.
- Existing ACTIVE four-hour Codex heartbeat: review-the-100-paper-trading-experiment.
- Independent $100 historical options account, two frozen comparison variants, separate
  cash/inventory journal, settled-cash enforcement and four-hour deterministic reviews.

## Observed verification

| Check | Result |
|---|---|
| Backend | 125 tests passed, including options accounting, data validation, reviews and isolated real PostgreSQL persistence; one upstream Starlette deprecation warning. |
| Python | Ruff clean; strict mypy passed for 25 files; earlier pip check passed, dependencies unchanged. |
| Frontend | TypeScript/Vite build passed; feed/storage and options cards inspected at 430px viewport without document overflow. |
| Isolated live probe | 18 seconds, no engine error, balanced accounting. WebSocket timeouts observed; REST worked. |
| Actual upgrade | Owned worker stopped and supervisor restarted it. Primary cash, funding, two closed trades and flat position state preserved exactly. |
| Journal | Independently balanced without projection mismatches; new research funding recorded separately. |
| Discovery | 52 USD spot markets screened. SUI, ADA, SOL and other candidates selected as observations changed. |
| Early performance | About 0.4% total-machine application CPU, 31 ms engine p95. PostgreSQL container around 66 MiB in a separate snapshot. |
| Raw growth | Roughly 0.9 GiB/day projected input during a short fallback sample; rolling retention means this is not daily disk growth. |

At 18:30 Denver, the tested resource-guard fix was running with six subscribed markets:
BTCUSD, ETHUSD, SUIUSD, ADAUSD, SOLUSD and DOGEUSD. Research was not constrained;
application CPU averaged 0.59% with 31 ms engine p95. The second owned restart again
preserved primary cash/funding/positions/pending/closed count exactly and reconciled.
Receipts: tiered-guard-before.json and tiered-guard-after.json.

The final checks include a clock-boundary fix: exchange-confirmed closed candles
persist even if local receipt time precedes the exchange close. Live observation
also caught an overly sensitive resource guard. It now requires four >100 ms samples
in the last twenty, or one >=1,000 ms stall, before a five-minute optional-research
reduction. Initial test-harness failures were corrected before the passing full run.

Evidence: docs/evidence/tiered-isolated-probe.json, tiered-ledger-before.json,
tiered-ledger-after.json, tiered-permanent-growth-sample.json, tiered-final-status.json
and the phone screenshots. Earlier receipts remain. Work is local and uncommitted,
with no remote, PR, deployment, exchange credential or paid call.

## Futures context checkpoint, approximately 18:55 Denver

The read-only Kraken perpetual context feature is now active. It records funding,
open interest and mark/index differences about once a minute, with explicit age,
units and unavailable/stale states. The dashboard displays the observations. Context
is linked to order/fill evidence and included descriptively in review windows; it
does not modify strategy signals, risk, cash or trade permissions.

Six assets passed the anonymous live public probe. A 16-second isolated integrated
run persisted context, had no engine error and reconciled; engine p95 was 31 ms.
The owned worker restarted at 18:54:22. Primary cash, funding, two closed trades,
positions, pending orders, attempt counts and replenishments were preserved exactly.
The running service then showed fresh BTC/ETH futures observations and a balanced
ledger. Additional tracked assets join subsequent collection cycles. At 430px the
new panel rendered without document overflow.

Receipts: futures-public-probe.json, futures-isolated-probe.json,
futures-before-restart.json, futures-after-restart.json and futures-final-status.json
in docs/evidence. futures-phone-context.jpg shows the actual phone-sized dashboard.
Two live context events were persisted at the last check; BTC/ETH open-interest
changes used approximately 60-second intervals and the ledger remained balanced.
Restart/persistence and order/fill context links passed isolated PostgreSQL tests.
A naturally triggered new trade and completed four-hour review containing futures
context remain future evidence. No predictive improvement has been demonstrated.

Only Kraken linear perpetuals are connected: no liquidation stream, CME/dated futures
or options chain. The user excluded futures orders; cash-funded options remain a
separate research hypothesis. No options simulator or broker account was created.
See [source, unit, storage and research details](research/2026-09-27-futures-context.md).

## Storage and remaining uncertainty

PostgreSQL is dedicated to this project at 127.0.0.1:55432. Preserve its volume,
trading-research-paper_paper-pg18. Financial events, bars, discovery scans, sampled
minute summaries and reviews are permanent. Raw feed data uses separate rolling
SQLite capture: 20,000 records / 64 MiB JSON payload, plus filesystem overhead.
Raw capture pauses below 5 GiB free; the financial journal is never pruned like raw data.

At 18:26 Denver a three-minute sample added 40,675 bytes of event bodies and 3,325
bytes of nonbootstrap candle bodies. That projects to approximately 20.1 MiB/day,
excluding indexes, journal lines, state rewrites, PostgreSQL WAL, backups and workload
changes. It is not a physical-disk forecast. Sustained load and backup/restore drills
remain unverified. Retention is not a backup.

No actual 100 ms push reception, full reporting period, strategy promotion, natural
replenishment or $1,000 attempt is proven. Synthetic tests cover mechanics only.
Fees remain 0.10% per side, adverse prices 2 bps, participation 10%, and minimum fill
delay one second. Real queue position, impact, execution and account entitlements
remain unvalidated. Faster observations do not prove better results.

Live options/commodities are not connected. IBKR's documented T+0 options balance
treatment remains an unverified lead, not the options simulation's cash-reuse rule.
See [broker findings](research/2026-09-27-brokers.md).

## Free historical options checkpoint, approximately 19:57 Denver

The latest free-only instruction supersedes paid-broker data as the initial path.
Anonymous Market Data AAPL historical calendar, chain and single-contract endpoints
were verified. The isolated integration probe consumed three actual historical
sessions and 178 contract observations with balanced accounting. No simulated fills
were manufactured in the running experiment. Full endpoint scope, assumptions and
learning gates are in [the options contract](research/2026-09-27-free-options.md).

The existing supervisor restarted its owned service at 19:52:23. All six existing
spot accounts preserved cash, funding, fees, realized results, closed/winning counts,
attempts, replenishments, positions and pending orders exactly. Spot and options
journals independently reconciled. The new options primary and its two frozen
variants each started with separate fake $100. The latest running check reached
May 26, 2026: five sessions, 356 contract observations, no completed trades, no fees,
no replenishments and no worker error. The calendar begins May 19 and has 90 sessions;
collection is bounded to 60 requests per UTC day and does not replay dates twice.

The $2.50 initial full-premium-plus-fee risk budget can exclude all otherwise useful
contracts. There are no historical Greeks/IV, intraday snapshots, live options fills,
covered sales or automatic exercise. Unknown expiry disposition freezes the account.
Reviews select among fixed policies only after sufficient completed evidence; no
options promotion, completed review, natural trade or $1,000 success is yet proven.
The first review is due at 23:52 Denver. The worker continues independently of this chat.

Receipts in `docs/evidence`: options-isolated-free-probe.json,
options-before-restart.json, options-after-restart.json and options-running-check.json.
The compiled dashboard's actual options panel rendered the separate account, source,
historical date, limits, review schedule and reconciled ledger in the local browser.
At 430px viewport width, document width was 415px (no horizontal document overflow).
`options-phone-account.jpg` shows the actual local panel. Nine initial options events
occupied 72,911 bytes of JSON bodies, excluding indexes, journal lines, projections
and WAL. This is a measured small sample, not a sustained physical-storage forecast.

Keep this machine and Docker running; sleep/shutdown interrupts local observation.
No public hosting is configured. See [feed/storage details](research/2026-09-27-feed-storage.md),
[experiment contract](LEARNING_EXPERIMENT.md) and [next checkpoint](NEXT_CHECKPOINT.md).
