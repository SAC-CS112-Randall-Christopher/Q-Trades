# Local crypto research agent harness

Current qualification work is recorded in the
[September 28 checkpoint](2026-09-28-local-model-qualification.md).
The application harness remains disabled while its candidate profiles are tested.

September 27, 2026. Design and model-evaluation work, not an enabled autonomous
research service. Chris explicitly requested an application harness with research
and training roles, welcomed LLM assistance, and authorized task-specific local
Python model tests. Crypto spot remains the first development focus.

The [completed local comparison](2026-09-27-local-model-results.md) contains measured
quality, latency, incomplete reasoning outputs and the resulting role recommendation.

## Responsibilities

| Role | Work | Appropriate implementation |
|---|---|---|
| Researcher | Form a falsifiable hypothesis, propose features/model changes and specify a comparison | A reasoning model, selected through task evaluation |
| Training worker | Build time-correct datasets, fit numerical prediction models, run replay and compute metrics | Python/ML tools; an LLM can draft the experiment specification |
| Independent reviewer | Challenge leakage, costs, multiple testing, unsupported claims and forward evidence | A separately prompted reasoning model plus deterministic checks |
| Operations analyst | Explain feed gaps, losses, resource usage and review outcomes | Code detects conditions; a small model can summarize evidence |

The training worker trains quantitative prediction models. The initial system does
not continually fine-tune an LLM on a few recent trades. Research memory stores
hypotheses, attempts, results and references; reading that memory does not change
the language model's weights. Distinct roles can share the same model weights and
run at different times. Multiple copies of one small model are not independent
confirmation of a research claim.

## Orchestration and permissions

Use an application-owned scheduler and persisted job queue, with explicit stages:

`new evidence -> hypothesis -> experiment specification -> numerical training/test -> review -> forward paper comparison -> promotion decision`

The scheduler handles four-hour reviews, new matured outcomes and failures. It sets
limits on jobs, proposals, retries, elapsed time, tokens and resource usage. Agents
cannot create unlimited child jobs. Start with one local inference request at a time;
execution and data ingestion have priority. A model timeout produces an unfinished
research job, never a stopped position manager or a fabricated conclusion.

Tools should return structured, source-linked evidence and calculation results.
The research roles can read a compact evidence packet, record a hypothesis, submit
a bounded experiment and read its report. They cannot change balances, erase losses,
change execution costs or risk permissions, or submit exchange orders. Generated
research code belongs in a separate resource-limited process with read-only datasets.
Strings retrieved from articles or model outputs cannot grant permissions.

The deterministic evaluator validates all experiment specifications and account
effects. An LLM critic is an additional review, not the authority on statistical
validity. Later-data comparisons and reproducible tests decide whether a candidate
earned promotion. This permits learning new relationships instead of merely choosing
one of the existing fixed strategy names.

Optional hosted reasoning is compatible with local application operation, but would
send selected evidence to a provider. No provider, API credentials or paid inference
budget has been selected. All inference in this assessment used the local Ollama
service and already installed weights.

## Hardware and existing evidence

Current inspection found an Intel Xeon W-2235 (6 cores/12 threads), approximately
96 GB system RAM, NVIDIA T1000 8 GB VRAM and Ollama 0.34.4. At inspection roughly
49 GB RAM and 6.5 GB VRAM were free. These are snapshots, not reservations or a
guarantee of sustained throughput. Several agents need not mean several GPU-resident
models; large contexts and concurrent requests consume additional memory.

Already installed models include Qwen3.5 2B (Q8_0), Qwen3.5 4B (Q4_K_M), Qwen3 8B
(Q4_K_M), Qwen3 14B, Phi4 Mini and Granite variants. Comparisons reflect these actual
quantizations, model generations and inference settings, not parameter count alone.

Chris's prior ArcGIS evidence was read directly from:

- `C:/GIS_AI/BexDog_Router_Benchmark_v3/bexdog_router_summary_v3.json`
- `C:/GIS_AI/BexDog_Router_Benchmark_v3/bexdog_router_benchmark_v3.csv`
- `C:/GIS_AI/BexDog_Router_Benchmark/bexdog_router_summary_v2.json`
- `C:/GIS_AI/BexDog-Router-Benchmark-v3.py`

The latest v3 run, dated September 24, used 31 prompts once per model, with thinking
disabled. After normalization, 2B passed 17 complete cases (54.84%), median warm
latency 3.984 seconds; 4B passed 18 (58.06%), median 7.2691 seconds. Reported field
accuracy and full-case accuracy are different metrics. Neither model produced an
unsafe execution error under that benchmark's gate definition, but both missed
fields/routes. This is evidence for evaluating small bounded helpers, not evidence
of financial research skill or general tool safety. No GIS project files were changed
or GIS prompt data sent to an external provider.

## Reproducible trading-research evaluation

Run from this repository:

```powershell
.venv\Scripts\python.exe scripts/benchmark_research_agents.py
```

Select one installed profile or a smaller case set with `--profile` and `--cases`.
Use `--thinking off` or `--thinking on` to override the profile's mode.
`--budget-seconds` bounds scheduling; an already in-flight request may extend the
overall run by its request timeout. Each request has a token cap and a timeout.
Two consecutive token-limited outputs skip the remainder of that profile. No model
download, API key, trading tool, account write or provider charge is part of the test.

The [v1 fixture set](crypto-agent-eval-v1.json) covers evidence extraction, four
training/evaluation defects, a clean forward-test candidate, cost interpretation,
experiment design, an untrusted instruction and failure diagnosis. Expected fields
were declared before execution. Structured-output conformity and exact-field scores
are recorded separately from completion and latency. Raw final responses are retained;
reasoning text is not needed for scoring and is not stored.

Scoring limits matter: declining all tools is an exact-task miss in the tool-planning
fixture, but is not an unauthorized tool action. Missing one review defect differs
from missing all of them. A superficially correct classification can still carry an
invented rationale. Read final responses and the per-field errors alongside totals.
Generated hypotheses require substantive human review; nonempty text is not proof of
novelty or financial usefulness. These development fixtures do not certify a model
for autonomous operation. Fresh withheld cases, repetitions and longer workflows are
needed before assigning consequential roles.

The earlier three-case smoke probe is retained at
`docs/evidence/local-research-model-smoke-2026-09-27.json`. A subsequent partial run
at `docs/evidence/crypto-agent-eval-20260928T032012Z.json` used zero-temperature
reasoning and was stopped after consulting the model documentation. Its observations
are preserved and must not be used to rank full reasoning capability. The revised
runner records vendor-recommended sampling parameters, actual quantization, corpus
hash, token limits, output completion and paper-worker health. Sampling changes do
not erase the prior outcomes or create independent trading evidence.

## Sources and architecture context

- [Qwen3.5 2B model card](https://huggingface.co/Qwen/Qwen3.5-2B): small-model deployment and intended task-specific/research use.
- [Qwen3.5 4B model card](https://huggingface.co/Qwen/Qwen3.5-4B): mode-specific sampling guidance; its much larger suggested generation budgets are not a claim that our smaller operational cap measures maximum capability.
- [Qwen3 8B model card](https://huggingface.co/Qwen/Qwen3-8B): reasoning/nonreasoning modes and explicit guidance against greedy reasoning decoding.
- [Ollama concurrency guidance](https://docs.ollama.com/faq): concurrent contexts and models require additional memory.
- [R&D-Agent-Quant](https://arxiv.org/abs/2505.15155): a research/development/feedback architecture reference, not proof of our venue or strategy performance.

See the [crypto learning plan](2026-09-27-crypto-learning-plan.md) for data,
chronological validation, execution costs and the first end-to-end model experiment.

## First implementation contract after qualification

Use three logical roles; weights may be shared. Compare quality first, then request
latency and resource use. A common model does not provide independent confirmation
simply because its reviewer receives a different prompt.

Keep one optional worker and one local inference request at a time. Run at most one
research cycle every four hours; do not run a text model for each price update.
Trading ingestion, position management and accounting remain separate. A role
failure is a failed or blocked research job, visible in the dashboard, and must
not restart or interrupt the paper worker.

Use a separate local SQLite journal for research jobs, stage events, model receipts,
experiment reports and consumed test-window boundaries. Financial history stays
in the existing database. Research reads public quote events through an explicitly
read-only PostgreSQL transaction with query/time/row bounds. Store event references,
snapshot identity and observation cutoff so each numerical run can be reconstructed.
Disclose any omitted older data. Stop optional work at a fixed storage cap; do not
delete failures or apply rolling market-data eviction to the research audit trail.

The first registered numerical tool is `quote-ridge-v1`: one approved feature,
one forecast horizon, training-only preprocessing, chronological purged test data,
equal versioned costs and a fixed ridge penalty. No arbitrary generated Python is
executed. A completed experiment consumes its test window even if the reviewer
rejects it. Repeatedly selecting on the same final test is prohibited. Insufficient
fresh examples produce a persisted waiting-for-data result.

The LLM receives a compact evidence packet with immutable source identifiers, data
availability, prior experiment references and relevant numerical results. It never
receives a database connection string or account credentials. Application code
maps validated role verdicts to its registered tools. The trainer/reviewer cannot
replace the selected feature, horizon, costs or risk rules in their output.

The reviewer sees the measured report and declared method; an earlier model's
enthusiastic explanation is not evidence. A `forward_paper_only` verdict is a
recommendation for another separately governed evaluation. It creates no account,
adds no fake funding and does not change the primary strategy. Quote-return labels
are not fills, trade-account returns, independent attempts or evidence of reaching
the $100-to-$1,000 objective.

The UI must show the actual role/model/mode, task, start time, elapsed time, input
evidence, concise final rationale, validated tool action, numerical result, review,
errors and next scheduled opportunity. Distinguish running, waiting for evidence,
failed and completed. Preserve completed and failed jobs across restarts. A stopped
job recovers as interrupted rather than silently repeating inference or a test.
Show API disconnection and stale status clearly; do not invent agent progress.

Before enabling this worker, verify qualified model digests and protocol/receipt
identities, a real three-stage evidence pass, enforced read-only data access,
interruption recovery, duplicate-cycle protection and the mobile dashboard. The
above is an implementation contract, not a claim that the worker or UI exists yet.
