# Finite operator paper-account setup — source proposal

The existing numerical supervisor gates both computation and funding on research
admission. This proposal lets a local operator launch **one already retained
paired proposal**, using the existing immutable request ID, policy and financial
writer. It creates at most two accounts per call. It does not create a research
question, run a numerical experiment or dispatch a model.

This is an optional source candidate. All ten Codex-selected, user-authorized
accounts were funded through the normal supervisor without an exception. The
#66 operating ledger retains their actual funding and normal-workflow receipts.
This route is not installed or needed for those operating requests.

## Runnable operator contract

`POST /api/autonomous/proposals/{existing_request_id}/launch` uses the existing
local-operator header and same-origin validation. Its body is:

```json
{
  "intent": "finite-paper-account-setup-v1",
  "expected_proposal_sha256": "<exact immutable saved proposal digest>",
  "expected_policy_sha256": "<exact frozen financial policy digest>",
  "maximum_accounts": 2,
  "allow_engine_work_recovery": false
}
```

The complete guard is the default. Changing the final field to `true` is the
separately reviewable policy candidate for this finite operator action. It is not
permission to install or execute the exception. No other field can select a
strategy, change funding, increase capacity, raise a quota or choose a model.
The actual retained user request IDs are:

- `codex-learning-20261006-lookback-5`: range reversion versus breakout.
- `codex-learning-20261006-lookback-15`: range reversion versus breakout.
- `codex-learning-20261006-lookback-30`: breakout versus range reversion.
- `codex-learning-20261006-lookback-8`: breakout versus range reversion.
- `codex-learning-20261006-lookback-22`: breakout versus range reversion.

These are ten distinct rule configurations across **two implemented signal
families**. All five accepted comparisons use the short horizon, unchanged
$100 fake capital per account, costs, risk, 2x volume and timing controls.
The earlier medium-12 request failed its causal-input requirement and was not
saved; long-24 was not submitted. Neither is silently retried or treated as an
accepted experiment. No win-rate or qualification benefit is established.

## Exact owner and recovery behavior

`AutonomousLab.launch_existing` verifies the saved proposal/policy hashes,
rejects completed or rejected evidence, and uses the existing `PaperStore`
transaction lock. The bounded source evaluation runs outside the financial SQL
transaction. Current executable-book freshness and the evaluation's age are
rechecked before funding. Evaluating a supported configuration does not assert
that its current entry signal is eligible; ordinary no-entry rules remain in force.

`PaperStore.lab_reserve` retains its permanent same-proposal reservation lookup.
An optional operator callback records the fixed intent, admission evidence and
allocated work, then calls the existing `finance.fund` inside that same native
transaction. A failure rolls back reservation and funding together. Existing
background callers omit the callback and retain their original behavior.

Reservation plus funding consumes two existing hourly work steps, or one when
an existing background reservation is being funded. Allocated seconds are at
least that phase count and include the measured preparation/reservation time
through the pre-funding check. Funding and commit duration are excluded from
that measurement; this is not an end-to-end performance result. Existing hourly,
daily, per-family and total-capacity limits remain enforced.

The PostgreSQL journal and SQLite inbox cannot share one cross-database commit.
Financial funding commits first, followed by the existing inbox acknowledgment.
The normal exact-ID GET now exposes `financial_outcome` from the immutable
reservation/funding events. If that shows a complete pair while the inbox still
says evaluated or reserved, the discrepancy is explicit. Repeating the same
intent can reconcile the inbox; it cannot add another pair or funding. A changed
intent, historical retired reservation or rejected/completed proposal is refused.
There is no automatic HTTP retry.

Use the existing continuous-research proposal inspection, trial history, Accounts
and Journal views to inspect the resulting records. No new frontend launch
control or standing model activation is introduced.

## Explicit pressure candidate

The candidate can remove only the `engine_work_recovery` veto for this finite
account-creation transaction. It retains the raw veto, complete diagnostic window
and current financial audit in its admitted-event evidence. The ordinary
background research, local-model and trading admission paths are unchanged.

The additional exception prerequisite is a current latest-20 work window with
the existing observation epoch and policy version, consecutive work numbers,
finite nonnegative durations, nondecreasing monotonic times no more than two
seconds apart, a last observation no more than two seconds old, and a matching
existing pressure-policy window. A closed policy must have a retained known
moderate or severe latency trigger from that owner. Startup, missing/stale work,
invalid/regressed clocks and unanchored severity stay refused. These are
candidate assumptions grounded in the current diagnostic fields and existing
two-second observation policy; they are not a financial response-time SLA or
proof of uninterrupted history outside the retained window. Coalesced notices
and trigger counts are not used to infer independent stalls.

Confirmed imbalance, unavailable/expired financial monitoring, stale/error paper
state, active replay/numerical ownership, recording failure, storage reserves,
actual exclusive writer, current
causal inputs, pauses, immutable rules, twenty slots and all financial budgets
remain protected. This does not change the 400/100-GB storage plan or any model
resource limits. A one-time account setup is not a measurement of model capacity
or simultaneous strategy usefulness.

## Verification and authorization boundary

The dedicated source tests exercise actual guard observations, native atomic
funding, financial/inbox lost acknowledgments, same-ID concurrency/reopen,
original prefixes, reserved-to-funded recovery and ten distinct configurations
within eighteen of twenty slots. Inputs and pressure are explicitly synthetic;
the native PostgreSQL schemas are disposable. Normal API inspection is exercised
through `TestClient`, not an operating browser or model.

The final affected native run passed all 33 cases without skips. It includes
actual API wiring that refuses active replay and numerical owners, and preserves
the original full `lab_inputs` evaluation and input serialization. Affected Ruff
and formatting checks, strict mypy for 110 source files and the diff check
passed. The exact disposable PostgreSQL process was stopped cleanly; its process,
listener and PID file were verified absent. These results remain source and
isolated-QA proof, not installed acceptance or permission to use the exception.

The first native run passed 29 cases but followed an identity-probe failure and
is retained with that setup limitation. The probe expected a bare address while
PostgreSQL returned `127.0.0.1/32`; canonical `host(inet_server_addr())` then proved
the exact disposable database/user/datadir/port before the affected rerun.
Prior failures and warnings remain in the private checkpoint receipts.

Publication of an unmerged draft does not authorize installation. Using the
explicit pressure option needs an additional decision approving the reviewed
source, its exact installed target and finite named launch requests. Operating
updates/restarts remain separate. Current normal-account funding is authoritative
in #66; no unchanged cooldown wait or operating retry is a prerequisite here.
