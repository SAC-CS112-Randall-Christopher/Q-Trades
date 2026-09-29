# Refining local models through an application wrapper

Chris asked whether Visual Studio, C# or a wrapper can refine the models. A C#
application can orchestrate the installed local models. Visual Studio is the
development environment; improvements come from the workflow, evidence, tools,
prompt contract and evaluation. This question does not by itself select a rewrite,
authorize new weight downloads or qualify a failed model.

## Three distinct kinds of improvement

1. **Application behavior:** constrained tasks, structured evidence, validated
   responses, registered tools, finite retries and recorded failure states. These
   can improve system reliability without changing the underlying model weights.
2. **Evidence and memory:** retrieve relevant past experiments, errors and measured
   outcomes from a local journal. Store hypotheses separately from verified facts.
   Retrieval gives the model context; it is not weight training or proof that a
   previously unprofitable idea is now useful.
3. **Weight adaptation:** later train a LoRA adapter on curated, correct examples.
   This requires a separate training dataset, compatible training weights/runtime,
   resource assessment and fresh evaluation. Existing quantized inference downloads
   do not establish training feasibility on this GPU. No training/download is started.

Microsoft documents local Ollama integration through `OllamaSharp` and
`Microsoft.Extensions.AI`, including interchangeable clients. Its AI libraries
provide tool invocation, telemetry and caching. Those are implementation building
blocks, not automatic scientific judgment or a profitability guarantee.
Sources verified September 28:
[local .NET integration](https://learn.microsoft.com/en-us/dotnet/ai/quickstarts/chat-local-model),
[AI libraries](https://learn.microsoft.com/en-us/dotnet/ai/microsoft-extensions-ai).

LoRA and related parameter-efficient training are documented in Hugging Face's
[PEFT quick tour](https://huggingface.co/docs/peft/main/en/quicktour). A C# interface
could coordinate a separate Python training process; changing the application's
language alone does not accelerate inference on the same Ollama model/backend.

## Recommendation for this application

Extend the current Python boundaries and local dashboard first, preserving the
existing tested numerical tools and paper engine. A C# controller or desktop UI
can call those services later if there is a concrete product need. No .NET runtime
or package was installed during this assessment.

The proposed wrapper should verify quote timestamps, label maturity, split
boundaries, equal costs and consumed test windows in deterministic code wherever
the evidence supports such checks. The LLM proposes bounded comparisons and
explains results; it cannot replace those checks or assume missing evidence exists.
The current `research_protocol`, `research_data`, `research_experiment` and model
receipt viewer implement prerequisites, not a completed autonomous harness.

Use a persisted sequence: collect evidence, propose one experiment, validate its
method, run a registered numerical tool, review the measured result, save the
outcome and next action. A waiting-for-data, rejected or failed result is a valid
terminal/waiting state. No model-created code, unlimited self-repair or retry until
the model approves. One inference queue, fixed budgets and paper-worker priority
continue to apply. Market-event ingestion and execution never wait for an LLM.

The UI should show actual inputs, tool calls, calculated results, concise final
explanations, uncertainties and failures, with recovery across restarts. It should
distinguish a deterministic guard blocking an action from the model recognizing
the problem itself. Neither output is a private chain-of-thought display.

## Preserve the experiment

Leave the active Qwen3.5 9B qualification and frozen v3 contract unchanged. Existing
Ministral/Qwen failures remain failures. Some are classification errors; others
concern substantive leakage or unequal costs, so a generic wrapper cannot be
assumed to fix everything.

If workflow or prompt changes are designed using the observed withheld failures,
give the revision a new identity and evaluate it on a genuinely new withheld set.
Measure both raw model judgment and complete workflow behavior, including bounded
tool misuse, unavailable evidence, interruptions, runtime impact and recovery.
Do not certify the original profile using a repaired response or recycled test.
The consumed real numerical test window ending at `1790595239.9180105` remains
unavailable for a fresh performance claim under any new wrapper.

The currently authorized path to an enabled advisory harness still requires
qualified profiles and substantive workflow checks. Weight fine-tuning is a later
candidate, not a prerequisite to building a useful local system. No LLM gains
authority over orders, balances, replenishments, strategy promotion or risk limits.
