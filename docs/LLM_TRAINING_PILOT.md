# Q-Trades LLM training pilot

Owner: issue #28, existing draft PR #41 (`codex/llm-training-pilot`). October 3,
2026 continuation integrates main `5cf37d3` and implements the required R1–R7
operator workflow. CP24 and the prepared v3 study remain frozen. The pilot does
not replace CP18 qualification or authorize training, installation or activation.

## Current operator workflow

Open **AI Lab → Training data**. Select a retained model attempt, numerical
episode, or market observation. Numerical/market observations have no original
LLM question or answer: enter a new question and author identity. Its authorship
time remains separate from original observation and receipt availability.

Inspect the original question, evidence, offered capabilities, timestamps,
unknowns, raw retained record and unchanged answer where one exists. Edit the
structured teaching target and intended lesson. A fresh-target button can replace
an invalid draft without changing the original answer. Save a draft, pending
reason or exclusion, or explicitly accept/correct after reviewing rights, facts,
families and reviewer provenance. New approvals require reviewer type, identity
and whether that reviewer authored the material. No human identity is inferred
for legacy records. Model-assisted instructional/interpretation review cannot
certify empirical trading performance.

Select saved examples, declare chronological cutoffs and run **read-only
preflight**. It reports problems by example together: unresolved provenance,
rights/timing, unsupported targets, duplicates/conflicts and protected families.
Different questions or capability contexts may share evidence; they still belong
to one related family. Coverage counts examples and distinct families separately
for useful proposals, waits, costs, negative/inconclusive results, refinement and
follow-ups. Draft, pending and excluded records cannot enter a corpus.

**Build reviewed corpus and prepare in Lab** freezes the reviewed selection,
exports its existing conversational prompt/completion format, imports through
the actual separate Lab, and runs the pinned Qwen3.5-4B tokenizer and effective
label checks. Preparation-only is explicit: it supplies training material while
independent validation/test remain unprovided. A full study requires all three
reviewed chronological splits. Only intended train/validation targets reach
preparation and the training preprocessing path; excluded final targets remain
unparsed. This application has no training-start or model-activation operation.

Open linked receipts from the same page, including after reload. Each new receipt
binds source example IDs, exact saved review revisions, dataset, base/profile,
study/run and local dispatch identities. Its links reopen those frozen reviews
read-only even after later corrections. Repeated preparation of the same frozen
selection reopens the original receipt. Interrupted attempts remain visible and
require an explicit retry. The initial handoff and attempt are committed together.
Retry claims the next attempt atomically in the existing registry, marks it
preparing before dispatch, and rechecks the frozen review fingerprint. Concurrent
callers cannot dispatch the same retry. The registry/financial lock is not held
while the Lab runs. Legacy interrupted creation with no attempt uses the stored
creation time for the same bounded wait and records its recovery explicitly.
Late completion updates only its owned attempt; newer claims/results and full
history remain intact. Missing archives are reported as unavailable, never
as newly verified. No partial bundle can overwrite a completed one.

An operator may also reopen a configured existing Lab evaluation. Its original
training dataset/model/run must match; it cannot be attached to the new prepared
dataset as though training occurred. The application displays measured semantic
components, requested/admitted/completed/usable coverage, grouped contrasts,
regressions, original mechanical flags, corrections and reviewer provenance.
Unavailable dimensions stay unavailable. Authority violations remain separate
from usefulness. None of these results establishes an individual example's
causal contribution, operating qualification or trading value.

## Configure the existing private Lab once

Use the existing Q-Trades and Lab environments and verified local paths. These
PowerShell placeholders refer to approved private storage, not a new disk tier:

```powershell
$qPython = '.venv/Scripts/python.exe'
& $qPython scripts/configure_training_lab.py `
  --lab <EXISTING_LAB_CHECKOUT> --private-root <APPROVED_PRIVATE_ARTIFACT_ROOT> `
  --base <PINNED_QWEN35_4B_BASE_DIRECTORY> --recipe <EXISTING_APPROVED_RECIPE_JSON> `
  --output <APPLICATION_DATA_DIRECTORY>/training-lab.json `
  --protected-corpus <SEALED_EXISTING_LAB_CORPUS> `
  --consumed-corpus <CONSUMED_EXISTING_LAB_CORPUS>
```

The command computes identities; normal reviewers do not copy hashes or answers
between applications. To link an existing measured comparison, also supply
`--comparison-run <RUN_JSON> --comparison-directory <PAIRED_RESULTS_DIRECTORY>
--semantic-review <FROZEN_SEMANTIC_REPORT> --comparison-id <LOCAL_LINK_ID>`.
Optional repeated `--review-history <ORIGINAL_REVIEW_OR_CORRECTION_JSON>` retains
old assessments, flags and corrections. Configuration updates preserve existing
retirements and comparison links. Source changes require explicit reconfiguration.

The server invokes only the fixed existing Lab command:

```powershell
<LAB_VENV_PYTHON> -m llm_lab.cli application-handoff <PRIVATE_ROOT> <OWNED_JOB_DIRECTORY>
```

The approved interpreter and Lab source are verified. The handoff uses offline
tokenizer access, no CUDA visibility, no weights, fixed arguments and a 180-second
bound. API clients cannot provide commands, URLs, paths or arbitrary reports.
An upload with a self-consistent hash is not proof of a Lab dispatch. Requests,
outputs and manifests stay private. The review tables share the existing research
registry; the Lab's original manifests/exposure history retain split authority.

Cross-study protection uses source content, original families and overlapping
windows (including different BTC/ETH tasks). It does not rely on filenames or
new target hashes. Explicit retirement preserves history and permits training/
regression reuse, never fresh evaluation. Sealed v3/operating material cannot be
retired through this workflow. Legacy manifests missing per-case window/split
keys conservatively protect all recorded families; their unknown relationships
are disclosed rather than claimed independent.

## Observed acceptance and limits

See the [R1–R7 ledger](reviews/llm-training-pilot/R1_R7_LEDGER.md) and
[current isolated verification](reviews/llm-training-pilot/2026-10-03-workflow.md).
One actual retained Binance.US BTC/USDT local receipt was copied read-only to
disposable application state with its original identity/time. The reviewed target
teaches missing-evidence interpretation. The prompt includes user-owned receipt/
identity diagnostics; raw exchange prices/depth remain private original provenance
and are excluded from the training input. It makes no BTC/USD execution, fill or
return claim. This is not the unfinished 2,700-second execution proof.

Actual Lab preparation measured 920 input and 148 supervised tokens (1,068 total)
with the pinned 4B tokenizer, thinking disabled, complete target labels, masked
input/padding and no truncation. No weight training was performed. The preserved
v2 comparison opens against its own original dataset and separate model review;
it is a reused historical instructional result, not fresh inference. CP24 was
neither rerun nor amended. Installed acceptance remains pending merge/install/
restart authorization.

## Earlier export-only slice (historical record)

## What the operator can do in this source revision

AI Lab -> Local model research -> saved task -> Model attempts -> **Export training
candidate**. Select the completed attempt, including a failed-but-retained answer.
The private export contains its original packet, original answer, role/stage,
cutoff and source grouping. It does not reconstruct historical inputs from current
market data. A pending/unknown response is not a training example. Missing archives
produce an explicit retry state; original evidence stays retained.

The export is deliberately **unreviewed**. It does not infer that a winning trade,
a positive review or valid JSON is a correct target. It does not copy model profiles
or credentials into the dataset. Source packets can still contain private research
material: save in the approved research storage, never the public repository.
Existing scoped outcome disclosure runs before export. No inference, funding,
account change, approval or weight update follows from downloading a candidate.

## Private review -> chronological corpus -> paired diagnostic

Use the project Python environment. Paths below are placeholders inside your
existing approved private research storage, not a request to migrate or create a
new operating storage tier. Each destination must be new. Output creation inside a
Git checkout is refused. A missing final manifest indicates an incomplete export;
retain it and choose a new destination after correcting the cause.

```powershell
python scripts/llm_training_pilot.py review-template candidate.json adjudication.json
# Read the packet, source records and original answer. Edit adjudication.json.
python scripts/llm_training_pilot.py review candidate.json adjudication.json reviewed-example.jsonl
# Collect explicitly reviewed lines in reviewed.jsonl without altering their candidates.
python scripts/llm_training_pilot.py build reviewed.jsonl private-corpus `
  --train-end <UTC_UNIX_SECONDS> --validation-end <UTC_UNIX_SECONDS> `
  --embargo-seconds <PREDECLARED_EPISODE_OVERLAP_BUFFER>
python scripts/llm_training_pilot.py verify private-corpus
```

The review must supply a corrected or explicitly accepted target, reviewer,
review time, rationale, data rights, synthetic/observed basis, failure categories,
all related episode/parent family IDs and availability for **every** evidence handle.
The target must be justified using facts already available at the decision. Later
matured outcomes belong in a later follow-up example, not an earlier decision's
inputs or reasoning. Review metadata is an attestation, not a cryptographic proof
that the reviewer is correct. Verify source records; never backdate unknown facts.

The builder reuses the existing `reviewed-rule-role-v5` prompt, exact packet wire
encoding and target validators. Stale contracts, unsupported actions/handles,
missing approvals/rights/timing, duplicate tasks or conflicting targets, related families
crossing splits, boundary-spanning episodes and protected qualification copies are
refused. Splits are chronological and never random per trade, row or seed. Choose
cutoffs/embargo before model comparison. Do not change them to obtain a good score.
The final manifest records role/category coverage and hashes all six dataset and
provenance files. Shuffled input ordering produces the same corpus.

Existing public development and acceptance packets are excluded using their
original generator; their source and thresholds stay unchanged. Exact/near-copy
checks do not prove semantic independence, detect every paraphrase, or eliminate
knowledge already present in pretrained weights. Manually review family grouping.
Do not call public procedural cases an unseen economic test.

## Curriculum: improve research quality, not trading activity

| Skill | Accepted target must demonstrate | Counterexamples to include |
|---|---|---|
| Evidence interpretation | Observed vs modeled vs missing, units and correct source references | Fabricated handles, stale books, unsupported fills |
| Hypothesis formation | One supported mechanism with a falsifiable comparison | Generic enthusiasm, irrelevant indicators, repeated unchanged tests |
| Comparative economics | Use authoritative whole-account after-cost results | Gross-only wins, idle cash/open losses omitted, double-subtracted fees |
| Causal reasoning | Availability at the actual decision, no future lesson retrieval | Revised filings, immature labels, overlapping episodes |
| Useful action | Propose valid bounded paper exploration when supported | Reject-all behavior, unnecessary waits, invented defects |
| Appropriate uncertainty | Distinguish insufficient data from disproved claims | Guaranteed returns, confidence without calibration |
| Independent critique | Assess frozen method/results, not persuasive researcher prose | Cost/horizon mismatch, untrusted instructions, stale parent |
| Follow-up selection | Preserve failures and choose a genuinely different useful question | Survivor-only stories, profit-based relabeling, duplicate trials |
| Supported capabilities | Pick exact offered rule/filter and wait dependency | Ridge-to-breakout translation, invented executable code |
| Operational boundaries | Recover from missing tools without financial authority | Funding/risk changes, hidden retries, falsified model success |

Build a reviewed seed set across both roles and action categories, including valid
proposals, correct rejections, inconclusive results and valid no-change decisions.
The earlier 500–1,500 example range is a collection hypothesis, not a sufficiency
threshold or a count of available examples. Grow by measured failure categories and
learning curves. Twenty correlated accounts do not supply twenty independent
confirmations. No real reviewed corpus has been established by synthetic tests.

## Training study to execute after data and compute qualification

Start with the unchanged installed Qwen3.5-4B as baseline. Verify a trainable source
checkpoint maps to the intended base weights and tokenizer; a quantized Ollama
runtime artifact is not automatically the trainable source checkpoint. Preserve the
installed baseline. No model download, paid GPU job, GIS/GPU reassignment or operating
restart is authorized by this source change.

First study: SFT with LoRA; compare modest ranks such as 16 and 32 only after an
architecture-compatible recipe and realistic memory profile. Use QLoRA only when
measured memory constraints warrant a separately verified configuration. These are
trial settings, not empirically selected optima. Avoid full fine-tuning, continual
pretraining and P&L-reward reinforcement learning as prerequisites for this pilot.

Use the frozen `train.jsonl` prompt/completion dataset. Verify the exact chat
renderer and assistant-only loss mask: no system/user/evidence loss, no duplicated
special tokens, no silent input or target truncation. Inspect token counts and
rendered boundaries using the actual tokenizer before any optimization. For Qwen3.5,
official Transformers documentation provides a distinct text-only CausalLM path;
do not blindly treat the multimodal checkpoint as another generic text config.
Record model/tokenizer revisions, template hash, precision, adapter targets,
optimizer, learning rate, batch/accumulation, seeds, steps, environment and hardware.
Choose checkpoints using validation, never the locked test. Compare against an
untuned well-prompted baseline with identical evidence/tools and operating budgets.
No training runner or completed weight update is claimed in this first source slice.

## Compare retained answers without hiding failures

Evaluate the two frozen profiles against the same reserved cases/seeds. Actual
inference must use the separately approved resource runtime; this offline tool does
not contact Ollama, another provider or a database. Record one row per requested
case/seed, including timeout/error/resource_wait. A missing row stays missing and
counts in the requested denominator. Do not retry until the preferred answer wins.
Each answer row has this shape (hashes below are placeholders):

```json
{"id":"candidate_sha256","seed":92811,"corpus_sha256":"corpus_hash","split":"validation","profile_sha256":"exact_frozen_profile_hash","status":"complete","answer":{},"wall_seconds":12.5,"tokens":220}
```

Use the full SHA-256 of the frozen profile, not a friendly model name. For incomplete
calls retain the status and set unavailable measurements/answer to null; do not
invent zero consumption. Preserve full original receipts separately.

```powershell
python scripts/llm_training_pilot.py compare private-corpus baseline.jsonl candidate.jsonl comparison.json `
  --split validation --baseline-profile <SHA256> --candidate-profile <SHA256> `
  --seeds 92811 92823 92837
```

The report compares contract/action/issue matches, critical violations, false
rejections, completeness and missing cases by role. It is **not** a semantic judge:
humans must review cited claims, selected capability/dependency, methodological
quality, usefulness and actual resources. No automatic role promotion, inference
activation, threshold waiver or profitability conclusion exists in this command.
The existing 34/36 and zero-critical actual role qualification remains separate.
Repeatedly inspecting test answers consumes them for further development.

## Economic proof is separate

Keep the existing A/B/C workflow definitions. Compare unchanged vs tuned model
within the same workflow before claiming the adapter caused a difference. Retain
all hypotheses and failures, same costs/capital/periods, open holdings/idle cash and
incremental research costs. Prospective frozen observations are needed for economic
claims; a lower training loss, more trades or better JSON score is not evidence of
an after-cost edge. The CP7 human/28-day policy and all paper-only limits remain.

## Sources used for the training design (checked October 2, 2026)

- Hugging Face Transformers Qwen3.5 model documentation:
  https://huggingface.co/docs/transformers/en/model_doc/qwen3_5
- Hugging Face PEFT quantization / QLoRA guidance:
  https://huggingface.co/docs/peft/en/developer_guides/quantization
- Hugging Face chat-template training guidance:
  https://huggingface.co/docs/transformers/en/chat_templating

These sources inform the next training study; they are not proof that the installed
checkpoint, masking, memory footprint or training performance has been verified.

## Retained software verification

See [the observed proof and failures](reviews/llm-training-pilot/README.md).
