# Resource-yield recovery and the requested restart

Chris explicitly requested restarting the qualification batch on September 28.
The new frozen continuation is `qualification-qwen14b-resume-20260928T173007Z`.
The original one-case trainer result from `research-roles-dev-20260928T164204Z.json`
is copied into a new evaluation receipt with its source SHA-256, runner hash,
completed-row count and original stop/finish timestamps. Its contents and original
receipt remain unchanged. Only the seven previously unrun development cases are
dispatched, with conditional holdouts after complete passing role screens.

The original batch had stopped between requests on the paper resource gate. The
default continuation rule still rejects stopped/finished evaluations. A new explicit
`--resume-resource-yield` path accepts only the exact known paper-resource stop,
with a finish timestamp, no active request and no disqualified role. It validates
the same model digest, runtime version/endpoint, prompts, corpus, seeds, inference
settings, request cap and ordered response prefix. Failed and incomplete rows are
retained as recorded; the first researcher failure is not included for retry.

The new scheduling policy, `resource-yield-v1`, permits up to **1,800 cumulative
seconds of resource waiting per evaluation stage**. The evaluator persists its
waiting reason, case, elapsed time and sampled health. Before dispatch after a wait,
resources must be clear for 30 seconds. The queue reflects `waiting_for_resources`
from the child receipt. Waiting consumes its separate budget; it does not reset the
600-second model request timeout. The pre-existing six-hour cumulative queue idle
budget remains unchanged. No additional model request is sent while constrained.

Only the paper optional-resource condition receives this bounded wait. A stopped or
unhealthy paper worker, unavailable model runtime, foreign resident model, changed
profile or invalid placement still prevents further inference. The wait history is
bounded at 128 episodes. Exhaustion remains a recorded terminal stop for review.
The single research inference lock remains held while waiting, preventing another
trading job from overlapping; it does not lock ArcGIS's separate runtime.

Prompts, model, six-thread CPU/IDLE-priority resource profile, zero-GPU policy,
decoding, timeout and role correctness gates are unchanged. Paper, accounting and
risk controls were not changed or restarted. No paid service, new weights or ArcGIS
configuration change was used.

Verification: 52 focused tests and 220 full-suite tests passed, plus Ruff, mypy on
34 source files and the web build. Tests cover immutable pass/fail prefixes, explicit
stop eligibility, in-flight/disqualified/profile/digest rejection, cumulative wait
limits, stable recovery, hard health failures and persisted waiting state. An
end-to-end simulated evaluator restart dispatched each case exactly once and left
the original receipt byte-for-byte unchanged. These are software tests, not new
model qualification or trading evidence.

Live checkpoint at 11:31:30 Denver: the continuation had one imported result and
`dev-trainer-future` in flight. The original prefix and source hash verified exactly;
the current model digest matched, GPU bytes were zero, and server/worker priority
and affinity matched the frozen allocation. Paper was running, fresh, error-free,
unconstrained, and balanced at journal revision 122001. The dispatch receipt is
`docs/evidence/qualification-qwen14b-resume-20260928T173007Z.dispatch.json`.
No new answer or real wait/recovery cycle has completed yet at this checkpoint.
Concurrent ArcGIS response-time effects remain unmeasured.

The existing 15-minute completion watcher was re-enabled for this continuation;
the four-hour paper/research follow-up remains active. Preserve this new source
archive and all older partial, failed, stopped and terminal receipts. The numerical
consumed-test boundary is still `1790595239.9180105`.
