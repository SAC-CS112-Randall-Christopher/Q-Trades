# Contrastive Language Models for the research harness

September 28, 2026. Chris's screenshot identifies **CLM-8B**, a Contrastive
Language Model. The earlier conversation supplied contract lifecycle management
text; that is a different use of CLM. This note addresses the actual model.

## What is supported by the primary sources

The [authors' model card](https://huggingface.co/Contrastive-LM/CLM-v0.1-8B)
describes two trained projection heads over a frozen Qwen3-8B encoder. It ranks
supplied candidates without generating text. Its scores are relative to the
candidate set; they are not calibrated probabilities of trading success.
Action representations can be reused while fresh states are encoded. It cannot
invent a missing action or supply the narrative research proposal by itself.
Its published coding-verifier results used specially fine-tuned heads, not the
released general head alone.

The [authors' implementation](https://github.com/Contrastive-LM/CLM) documents
a roughly 75 MB head **plus** the Qwen3-8B encoder, with a vLLM pooling server in
the reference setup. The head must match the encoder and last-token pooling.
The headline up-to-9x latency result concerns the authors' selected agent tasks;
their coding-verifier timings used an H100. These are not measurements on this
Windows workstation or on a trading system. The reference defaults truncate at
2,048 tokens; a local adapter must reject or explicitly report truncation.

The [community GGUF port](https://huggingface.co/czl/CLM-v0.1-8B-GGUF)
publishes its own precision comparison. It reports lower ranking accuracy with
Q4_K_M and does not recommend that variant for ranking. Its encoder sizes include
8.71 GB for Q8_0 and 7.03 GB for Q6_K, plus heads/runtime. Those are the port
author's measurements, not our independent reproduction. An installed generic
Qwen3-8B Q4_K_M model is not automatically an equivalent CLM deployment.

## Fit for this project

Promising research candidate: compare a CLM router with deterministic routing and
the qualified generative agent on a fixed set of research actions. Include
request-more-data and abstain, invalid/missing evidence, contradictory methods,
and unseen combinations. Audit state freshness, candidate-set changes and cache
invalidation; never reuse a previous market decision as though it were fresh.

Measure cold and warm latency, p50/p95, peak memory, accuracy and unsafe approvals
under identical packets. Candidate choice order must not determine correctness.
Test performance with concurrent paper ingestion. Do not infer research novelty
or financial skill from successful routing.

The generative researcher proposes an experiment; numerical code trains and tests;
a reviewer challenges the evidence. CLM could assist a bounded selection step if
it improves those measured outcomes. The present four-hour research cadence does
not justify putting an 8B text encoder in the order-handling path. Position sizing,
limits, quote freshness and exits remain deterministic. Learned numerical models
may eventually score market features quickly after separate forward validation.

The UI would show available choices, scores, selected action, source evidence and
the actual tool result. Any explanation written by another model must be labeled
as that model's summary; CLM does not emit a reasoning transcript.

## Local availability and authorization

Observed workstation: NVIDIA T1000 8 GB, Windows, Ollama. The project's Python
environment has no torch, transformers or llama_cpp; llama-server is not on PATH.
Compatibility and memory use therefore need a separate implementation assessment.
The tiny head size must not be presented as the total installation requirement.

No CLM weights or runtime were installed. Chris explicitly approved Qwen3.5 9B
and subsequently Ministral 3 8B Reasoning; both downloads succeeded and their
receipts are retained. Other model downloads still need his
approval. A CLM experiment would be isolated from the
paper journal and would not grant account or order authority.
