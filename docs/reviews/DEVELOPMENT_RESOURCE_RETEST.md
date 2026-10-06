# Explicit append-only development resource retest (#66)

The original trained-v2 attempt failed and its allowance and execution permission
are consumed. PR #69's resource-owner repair was merged as
`38836fcf335261c9a96b9b68aef1237227ff2aaa`. Installing that repair does not make the
original failed question dispatchable or authorize another model call.

This follow-up adds a source capability for one separately authorized resource
retest of the same retained development question. Source and disposable
procedural verification are the current scope. No actual permission receipt,
private-registry change, model execution, installation, restart, question,
training, qualification, RAG, operating activation or paid/provider call is
created by this work.

## Existing owners and immutable accounting

`RoleWorker.development_answer` keeps its existing default failed-request refusal
and cached successful-answer behavior. The optional
`resource_retest_authorization` argument enables a narrowly bound append-only
path. It is not the existing operating `retry()` method: that method changes
the prior attempt's status and is intentionally not used here.

The retest requires exactly one attempt in the same development stage, numbered
one, with failed status and a finite finished timestamp. Its original response
must contain exactly the fifteen public fields emitted by the pinned transport
receipt, with no missing or extra fields. It must be a pure
`development_transport_failure` marked cancelled and incomplete,
with a known integer child exit code, child termination, verified cleanup with
no cleanup errors, and a retained private dispatch receipt. There must be no
`answer`, `raw_answer` or answer-bearing `transport_failure` annotation. Unknown
completion, successful or invalid answers, incomplete ordinary model responses,
other failure categories and unverified cleanup cannot use this path. The task
must remain idle, hot and in its unchanged stage; operating research stays
disabled.

Before reservation the existing development admission runs the complete paper
guard and returns the existing full serving profile. Packet compatibility and
input bounds use the existing preflight. The current profile must equal the
original attempt's full profile; no grant fields are put in PROFILE or the
packet. Existing hourly wall/token accounting remains authoritative and includes
the original full reservation while it falls within that window.

Inside the existing `BEGIN IMMEDIATE` transaction, the worker rechecks the task,
prior attempt, source bindings, authorization expiry, deadline and disabled
research state. It inserts attempt two in the same `development_*` stage and
appends a `development_resource_retest_reserved` event with the supplied caller
evidence and its fingerprint. These writes commit or roll back together. The
existing `(task, stage, attempt)` key, exact prior binding and recheck prevent
concurrent duplicate reservations. No new table, view, migration or scheduler is
introduced. Grant identity is scoped to this bound task/stage; it is not a new
global grant registry or cryptographic proof of human permission.

No prior attempt, allowance, task, frozen packet or metadata is reset or updated.
Once attempt two is reserved, failure, cancellation or unknown completion cannot
authorize attempt three. The new attempt uses existing response/failure and cost
retention. A late original answer is retained with failed status if cancellation
or its deadline won the race; it is not exposed as a successful cached retest.
The existing normal task detail API reopens both attempts. Development stages
remain excluded from teaching export and cannot advance paper trials or become
qualified operating answers.

## Bounded caller evidence and CLI handoff

The existing CLI accepts optional
`--resource-repair-retest-authorization PATH`. It still requires
`--authorized-development-inference`, an existing expressly prepared development
registry/marker with operating policy absent, and a finite future
`--cancel-at-monotonic` for a retest. The CLI refuses bad caller evidence before
constructing a registry. It reads at most 8 KiB from a local regular path and
rejects unknown fields, malformed identities/hashes, nonfinite expiry and a
different task.

`ResourceRetestAuthorization` is a strict frozen object with these fields:

| Field | Binding |
| --- | --- |
| `format` | Literal `qtrades-development-resource-retest-v1`; exactly one additional attempt |
| `grant_id` | Bounded caller reference to the separately retained human grant |
| `task`, `stage` | Existing task and its `development_idea`, `development_review` or `development_followup` stage |
| `task_sha256` | `experiment_registry.fingerprint` of the complete raw task row, including context |
| `prior_attempt_sha256` | The same fingerprint of the complete raw original attempt row, including its exact serialized response and original reservation |
| `packet_sha256` | Existing `fingerprint` of the original and current packet objects |
| `profile_sha256` | Existing `peft_profile.digest` of the full original serving profile; also matches its failure receipt |
| `owner_source_sha256` | Raw byte SHA-256 of the current `peft_child_owner.py` |
| `transport_source_sha256` | Raw byte SHA-256 of the current `peft_role_model.py` |
| `expires_at` | Finite positive Unix UTC seconds; must remain in the future at admission |

Packet/row fingerprints and the compact profile digest are different established
algorithms. Source hashes bind actual bytes, including line endings. The task and
prior-row values are obtained only through a separately authorized bounded
inspection; this implementation does not prepare an actual grant or inspect the
original private registry.

The finite monotonic deadline cannot be more than the unchanged 600-second
profile limit away. It is checked before admission and again before reservation
and inference. The worker uses existing cancellation/transport cleanup ownership
on expiry; the CLI does not add a second timeout cancellation while that cleanup
is running. The one existing development drain shields the original inference
task through further external cancellations, retains its returned answer or
measured failure receipt, then propagates the first interruption when an answer
completes. Cleanup must be allowed to finish and retained as observed. This is
not a hard total wall-time or continuous coexistence guarantee: a future finite
session must still reserve guard/cleanup time, enforce its outer bounds, observe
actual runtime and retain deadline overruns or incomplete coverage honestly.

The receipt and CLI flag are caller evidence of applicable separate authority.
Their existence is not human permission, installed acceptance, a resource
measurement or model-capacity proof. They do not extend the consumed original
grant. This capability is development CLI-only. The existing paper owner is
already installed at the repaired `38836fcf` target; another paper update or
restart is not a prerequisite for invoking the exact reviewed development
worker/CLI source. Do not repeat that completed rollout for this capability.

A new finite model attempt still needs explicit human approval for that exact
reviewed worker/CLI source and invocation, the repaired owner/transport byte
hashes, and the same private task, packet, full profile and complete guard.
Source module/path identity must be pinned by the separately authorized caller.
Any requested merge or operating installation/restart remains a separate action;
none is performed here. Preserve the failed attempt and allowance permanently.

## Verification and remaining limits

Focused fixtures use synthetic SQLite rows, synthetic caller evidence and
procedural transport responses. They exercise append-only accounting, default
refusal/caching, exact bindings, expired/missing/invalid deadlines, closed full
guard, hourly allowance, changes during admission, concurrent duplicate calls,
atomic event rollback, second failure and owned cancellation with late/unknown
completion. Actual normal GET handlers reopen both attempts and the typed
training endpoint continues to reject development stages. No model, original
registry, financial database, server or provider is used.

The final focused Windows fixture run passed 84 cases with zero skips in 5.96 seconds.
This selection includes the new retest tests, existing development preflight and
the three existing CLI deadline/default-route tests. Affected existing PEFT
development, failure-receipt and role-worker regressions passed 20 cases in
14.86 seconds; 17 dedicated-PostgreSQL cases were explicitly skipped with
`QTRADES_TEST_DATABASE` intentionally absent. One unchanged, previously accepted
native child-lifetime fixture was deliberately deselected. Each run reported the
same existing pinned Starlette/httpx deprecation warning. The PostgreSQL skips
do not establish new database-backed regression acceptance.

Failures remain separate from those passing selections. The initial focused
run had two test-expectation failures: the typed teaching route correctly returned
422, and an elapsed admission deadline correctly raised `TimeoutError`.
A single pre-repair repeated-cancellation counterexample failed because the
second cancellation abandoned the owned inference drain. The final parametrized
case passes for both original development dispatch and the retest, retaining the
late response and failed accounting. A later selector setup error executed no
tests; the corrected final selection is the 84-case run above. Logs, XML and the
pre-repair source hashes are retained in task-owned QA output.

Ruff passed for all source, scripts and tests; formatting passed for the three
changed Python files. The repository-wide Ruff pass warned about two pre-existing
inaccessible pytest temporary directories; the explicit source-path pass had no
such warning. Windows type checking passed for all 109 source files including
the CLI. Independent review is reported with the final source receipt.
These tests establish software behavior only; actual model success,
repaired installed coexistence and capacity remain separate and unproven by this
capability.
