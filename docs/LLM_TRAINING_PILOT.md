# Q-Trades LLM training pilot

Owner: issue #28. Requested by Chris on October 2, 2026. This bounded source lane
starts from main `9d45f71`; PR #40 owns operating receipts and is unchanged.
The pilot does not replace or delay CP18's first real qualified research cycle.

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
missing approvals/rights/timing, duplicate same-role evidence, related families
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
