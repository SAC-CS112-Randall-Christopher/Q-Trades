# Trained-v2 development serving — issue #48 / operational CP18 under #28

The selected implementation directly reuses the private Lab's frozen
`load_base`, `tokenizer_at` and `verify_model` functions, then loads the saved
PEFT adapter with `is_trainable=False`. It does not run the Lab's paired evaluation,
read a corpus/holdout, train, export, start Ollama or substitute an unchanged GGUF.

The target is the named `qtrades-crypto-researcher-4b-v2` candidate, selected step
80, against Qwen/Qwen3.5-4B revision
`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`. Bounded read-only alias/run metadata
agrees with the completed v2 run; this is linkage evidence, not actual serving.
The private base identity is pinned in the operator configuration/attempt receipt.
Neither weights, private paths, corpus material nor run contents belong in Git.

## Current authorization and admission

The human has authorized one actual attempt with the profile below. The real
backend's `development_admit` refused engine-work cooldown on October 5 at
00:09:20 UTC, before model imports/loading, a role question or allowance
reservation. The attempt remains unused; do not ask again for that same profile.
See [issue #48 comment 5985924232](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/48#issuecomment-5985924232).
[RAM_ASSISTED_CAPACITY.md](RAM_ASSISTED_CAPACITY.md) records the bounded capacity
repair; it does not override admission or change this approved model profile.

## Frozen authorized development profile

| Setting | Declared value |
| --- | --- |
| Backend | Lab Transformers + PEFT, one owned child, inference only |
| Host/placement | Windows CPU only, two logical processors, IDLE priority |
| Precision/quantization | float32 / none |
| Threads | PyTorch 2; interop 1; bounded BLAS threads; tokenizer parallelism off |
| Decoder | Greedy, seed 92811, thinking disabled |
| Context/output | Complete tokenized packet + 1,024 output tokens must fit 8,192; no truncation |
| Call budget | 600 seconds including parent-supervised import/verification/load/response; bounded termination/guard-query overhead is separately recorded |
| Memory | Supervised 24 GiB child RSS ceiling; 8 GiB available-memory reserve; require 32 GiB available before launch |
| Allowances | Existing role ledger: 1,800 wall seconds / 65,536 tokens per hour; each attempt reserves 600 seconds / 8,192 tokens |
| Package pins | Python 3.12.10; torch 2.14.1+cpu; Transformers 5.18.0; PEFT 0.21.2; Accelerate 1.15.0; Tokenizers 0.23.2; Safetensors 0.8.0 |

CPU float32/unquantized serving differs explicitly from the CUDA float16/NF4
training recipe. The inference context allowance also differs from training's
2,048-token preprocessing limit. No training/qualification result transfers to
this new profile. Actual compatibility, load/response time, peak RAM and protected
work impact remain unmeasured because the unchanged guard has refused admission.
The memory allowance provides float32 weights plus loading/runtime headroom;
it is a declared conservative development budget, not an observed requirement.

## Existing workflow and response boundary

Create one question through the ordinary Local model research workflow in a
separately declared development environment with operating roles disabled.
`RoleWorker.development_answer` builds the same frozen normal role packet and
records the attempt in the existing role history and allowance ledger. The
transport uses the Lab's configured interpreter/source and offline/local-only
loading. It verifies base bytes/revision, complete text loading through the Lab,
adapter membership/hashes, active unmerged adapter, exact canonical loaded adapter
tensors against the frozen checkpoint, frozen CPU parameters,
package versions and the training tokenizer template.

The original model text, parsed answer, stop reason, identity, placement, token
counts and timings survive before application contract validation. Invalid or
incomplete answers stay failed with their original evidence. Private job receipts
retain model/identity/size failures too; an attempt's reason includes the opaque
job ID. Unknown attempts cannot silently repeat. Cancellation retains an answer
that wins the race and preserves its costs.

Development stages are named `development_idea`, `development_review` or
`development_followup`. The ordinary task does not advance, no comparison is
created, and `_answer` cannot reuse an unqualified development response. This
transport's operating `admit` always refuses. Existing role detail/history reads
expose the attempt; no new dashboard feature or second research registry exists.

The normal research-inference lock enforces one model job at a time. A Windows
job bound to the original child handle closes on supervisor exit, including a
crash; the child waits for ownership before importing/loading a model. Timeout,
memory pressure, cancellation and the unchanged full paper guard stop only the
owned child. Standard error/output and private requests/results are bounded;
no financial lock is held over inference. The guard is checked before dispatch
and during the call. A final original answer is preserved if the guard closes
as it arrives, without granting that answer operating authority.

## Operator preparation after applicable authorization

Use the existing development application and an explicitly owned private
development registry, never the installed registry or financial accounts.
Copy its reviewed `training-lab.json` configuration, retaining the exact private
Lab source identity/interpreter. Record `development-environment.json` with
format `qtrades-owned-development-v1` and the absolute existing registry path.
The directory must contain no `role-policy.json`.

Declare `development-serving.json` with exactly these fields:

```json
{
  "format": "qtrades-peft-development-v1",
  "candidate": "ABSOLUTE_PRIVATE_ROOT/named-models/qtrades-crypto-researcher-4b-v2.json",
  "candidate_sha256": "SHA256_OF_THE_EXACT_ALIAS_FILE",
  "run_sha256": "SHA256_OF_THE_EXACT_SELECTED_RUN_JSON"
}
```

The alias and run must agree with the frozen selected base/adapter. No arbitrary
model path, GPU profile, new runtime command or inferred qualification is accepted.
Set `PYTHONPATH` to the reviewed Q-Trades checkout's absolute `src` directory so
the application interpreter imports this source rather than the installed release.
After creating the normal question, use that interpreter to run
`scripts/answer_development_role.py --registry <owned-registry> --task <question-id>
--authorized-development-inference`. The flag records operator intent; it does
not substitute for the user's applicable authorization or bypass the full guard.
The private job keeps its exact request/response/dispatch receipt, and the normal
question detail retains the original answer. Do not turn on operating roles.

## Observed source/procedural verification

The targeted new selection passes **24 cases**: normal questions through the
actual transport/registry using an explicitly procedural child response; exact
original response and cost retention; disabled operating dispatch; incomplete,
invalid and unknown responses; late completion versus cancellation; live owned
child termination; timeout/pressure/guard interruption; source/alias drift; and
procedural loader checks for wrong package/template/adapter/device/precision/context,
missing adapter tensors and mismatched tensor values before generation.
All model objects/responses in these tests are fixtures. No trained weights or
real model libraries were imported for them. Native ownership tests use ordinary
disposable Python children, not a model service.

After the final tensor-identity check, the new cases and existing role worker,
supervisor, history, packet, readiness and local-role regressions passed together:
**77 cases** in 77.12 seconds, using isolated password-authenticated native
PostgreSQL, with the existing Starlette warning.

Ruff and strict Windows-targeted mypy pass. The combined native suite at
`894879270736a310e75df1bbc421d126351c6f20` passed **1,014 cases, one skip** in
439.49 seconds, with the existing Starlette warning. That full run includes the
final capture repair and precedes the final adapter-tensor equality check. The
later focused selection and exact-head hosted receipts are reported separately
in the owning draft/issue; the earlier full run is not a claim about that new head.

## Capacity evidence and remaining milestone

The rollout's six retained observations contain **105 distinct engine-work
samples**, de-duplicated by original timestamp. **15 exceed 100 ms; none reach
one second.** These are sparse retained windows, not a continuous tail estimate.
Median/p95 milliseconds (nearest lower sample, reported separately per stage):

| Stage | Median | p95 |
| --- | ---: | ---: |
| Complete transaction | 61.471 | 115.384 |
| Projection read/decode | 25.807 | 53.484 |
| Projection update | 17.964 | 40.337 |
| Database commit | 2.980 | 15.807 |
| Projection encoding | 7.573 | 14.196 |
| Financial calculation | 0.912 | 1.952 |
| Writer-lock wait | 0.002 | 0.004 |
| Compact capture enqueue | 0.020 | 0.031 |

The recorded work is dominated by the projection/database stages, not financial
calculation or capture enqueue. Separate percentiles are not additive. These
measurements do not identify disk/controller or PostgreSQL internals as the cause.
The fresh read-only check also reports a running, fresh, error-free paper engine,
recording capture, unchanged counter epoch, and admission refused by
`engine_work_cooldown`. No threshold/cooldown or source/operating policy was changed.
A metadata-only Windows memory observation reported 65,325,604,864 available
bytes, exceeding the proposed 32 GiB launch requirement at that instant. This
does not measure v2's load/response memory or establish sustained capacity.
A new unchanged wait is not proposed as a capacity experiment.

Next actual acceptance is one explicitly authorized trained-v2 development
attempt when the entire unchanged guard admits it, yielding either the original
verified response or an exact retained compatibility/resource failure. Current
admission is still refused; source/fixture passes do not authorize an override.
Current independent 4/4 development for both roles, 36 completed / at least 34
correct / zero critical violations per role, qualified ordinary paper feedback,
genuine maturity/continuation and CP23 usefulness/sustained observation remain
separate incomplete stages. The six-PR rollout remains completed and unchanged.
