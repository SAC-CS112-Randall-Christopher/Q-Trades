# Ministral 3 8B Reasoning: local comparison

September 28, 2026. Chris approved this additional download. No other model
download, paid inference, firewall change or trading permission is implied.

## Installed artifact

Official [Mistral GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512-GGUF),
Q4_K_M: 6,057,194,337 bytes including the vision projector and metadata. Installed
tag `hf.co/mistralai/Ministral-3-8B-Reasoning-2512-GGUF:Q4_K_M`, digest
`2b654ed98a09be0346a2a07c12b077714a8b5eca06abbe1b90291909822718a5`.
The completed download left 20.02 GiB free at 04:11 Denver. The original model
is retained. Receipt: `docs/evidence/ministral3-8b-download-20260928T100030Z.json`.

The [provider's model card](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512)
recommends temperature 0.7 and its supplied system prompt. The API examples use
top-p 0.95. These are configuration guidance, not evidence of financial skill.

## Compatibility and development evidence

Ollama 0.34.4 advertises completion/tools/vision but no explicit thinking control
for the imported artifact. `/api/show` exposes the embedded native reasoning
template, despite the simpler legacy template in the public download manifest.
The arithmetic compatibility probe verified separately parsed reasoning plus
schema-constrained JSON, with the correct final result. No parser replacement or
Ollama-server restart was necessary. Probe receipts:

- `docs/evidence/ministral3-8b-compatibility-probe.json`
- `docs/evidence/ministral3-8b-structured-compatibility-probe.json`
- `docs/evidence/ministral3-8b-runtime-metadata.json`

The first v3 role screen used the task system prompt without the provider prefix.
Although `--thinking` requested a reasoning budget, all 12 responses had **zero
separate reasoning characters**. Treat these as observed direct outputs, not a
verified reasoning-mode comparison. Researcher passed 4/4, trainer 2/4, reviewer
3/4. The trainer unsafely approved unequal costs; this profile is not eligible.
Median role times were 16.82 / 15.91 / 14.36 seconds. Receipt:
`docs/evidence/research-roles-dev-20260928T101449Z.json`.

Manual rationale inspection also found an unsupported claim that order-flow
observations are required for all the listed price/spread features. Exact-field
passes therefore do not certify every narrative assertion or research quality.

The next profile prepended the official, unmodified
[SYSTEM_PROMPT.txt](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512/blob/main/SYSTEM_PROMPT.txt)
to the unchanged role contract. The scientific cases and oracle are unchanged;
no withheld Ministral case had been submitted. The prefix is stored with SHA-256
`aba1efaff0bdc73f4a864139e2c07dce8fc1e3df7b5d5c2b2623df6816697156`.
Effective prompts now have their own identity, checked by the qualification gate.
The existing Qwen prompt identity remains unchanged.

This native-prompt screen retained two outcomes: one 120-second timeout and one
correct response at 91.23 seconds. It was interrupted to investigate resource
allocation; an in-flight request is unresolved. Do not call it a complete quality
comparison or erase the timeout. Receipt:
`docs/evidence/research-roles-dev-20260928T102024Z.json`.

## Text-only configuration of the same weights

The runtime log showed 31/35 layers on the GPU, an 818.51 MiB vision projector,
and 818 MiB of language-model tensors on the CPU. These tasks contain no images.
A local alias imports the already approved language-model blob, omits the image
projector, and uses a 6,144-token context instead of 8,192. It retains the same
Q4_K_M text weights, 4,096-token generation cap, two CPU threads, temperature 0.7,
top-p 0.95, top-k 40 and the official reasoning prefix. This is a new inference
profile; results must not be silently pooled with the original profile.

Alias: `trading-research-ministral3-8b-text:q4km-v1`.
Digest: `d2158820e07fe3d4cddd5910889b92d549feb9942f5d2edbc5ec30b06b1f5502`.
Creation used an existing blob; observed disk change was 4,096 bytes, not another
5.2 GB weight download. The original image-capable installation remains present.

`/api/ps` then reported all 5,863,699,905 bytes of the text profile's model allocation
in VRAM. This is an allocation observation, not yet a measured speedup. Sampled
paper health was running, nonstale and error-free; engine p95 was 63 ms. Receipts:

- `docs/evidence/ministral3-8b-text-profile-creation.json`
- `docs/evidence/ministral3-8b-resource-check.json`
- `docs/evidence/ministral3-8b-text-resource-check.json`
- `docs/evidence/research-roles-dev-20260928T102522Z.json`: completed development run.

All 12 text-only native-prompt requests completed and emitted a separate reasoning
output. Maximum prompt size was 1,125 tokens; the 4,096-token generation allowance
fits within the 6,144-token context without needing input truncation for these cases.
Researcher passed 2/4, trainer 4/4, reviewer 2/4, with zero unsafe approvals.
Median role times were 48.44 / 82.84 / 45.86 seconds. The first researcher case
completed in 57.84 seconds, compared with the original profile's 120-second timeout.
This small comparison changes both projector loading and context allocation; it
does not isolate their individual effects or establish a general speed multiplier.

Only the training role warrants withheld acceptance from this screen. The trainer
now correctly rejected unequal costs and requested missing outcome labels, where
the direct-output configuration failed. Its latency misses the preferred 45-second
target; any future use would be occasional background research, never trade execution.
Research/reviewer failures included unsupported extra issue classifications.

No model is qualified at this checkpoint. No research harness is enabled, and no
LLM output authorizes a financial action. A separate read-only model-testing UI is
now available. The next decision uses complete role evidence, latency, substantive
rationale review and withheld tests.

Trainer acceptance began at 05:35 Denver with a 300-second per-request allowance
declared before any withheld input was submitted to this model/role. Sampling,
native prompt, context and output cap are unchanged. The expanded allowance is
for occasional background analysis. Freeze:
`docs/evidence/ministral-trainer-freeze-20260928T113548Z.json`; results:
`docs/evidence/research-roles-holdout-20260928T113553Z.json`. At the 05:46 checkpoint
nine responses were retained, eight correct; unavailable labels were incorrectly
rejected and classified as missing forward evidence. No unsafe approval was observed
in those nine responses. This partial result cannot qualify the model.

At 05:55:05 Denver, the run finished with **13/16 correct** and three failed cases,
making 34/36 unreachable. Missing labels were incorrectly classified in two seeds;
another answer found test reuse but missed simultaneous preprocessing leakage.
No critical violation was observed in the retained cases; unrun cases are unknown.
Median request time was 66.875 seconds. The qualifier refused incomplete coverage.
Recomputed result and original receipt hash are retained in
`docs/evidence/ministral3-8b-trainer-disqualification-20260928.json`.
This profile is disqualified under the frozen contract. No prompt or grading
threshold was changed to obtain a pass.
