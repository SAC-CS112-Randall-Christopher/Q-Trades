# F3 follow-up: discovery while a proposal waits

This addresses only the second review's remaining P1 follow-up at
[PR24 discussion 4150167727](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/pull/24#discussion_r4150167727).
The inspected source is `16c612804d19a162a8994fe815af4f2f42406fa1`.
The original eight-request checklist and earlier audit receipts stay in place.

## Predeclared acceptance

- In disposable PostgreSQL, preserve a promising frozen breakout parent, set
  `family_slots=2`, and submit one valid breakout replication. With six protected
  originals and one retained parent, thirteen total slots remain free. Its family
  wait must not prevent the controller from generating, evaluating, reserving and
  funding an independent range-reversion pair through normal passes. Do not submit
  that independent proposal manually or replace the real generator/admission path.
- Retain the blocked proposal, frozen parent contract/rules/risk/funding, rejection
  history and its original future retry. No premature retry or duplicate funding.
  Restart retains the deferred job and later eligible retry can proceed.
- Four evaluated/reserved/blocked proposal jobs remain the queue bound. A full
  deferred queue must not issue another discovery bundle/proposal; use its retry
  for the next wait. When discovery has no eligible idea, retain that same retry.
- Existing resource, hourly/daily budget, pause, storage, data and sole-writer
  admission gates still apply. Verify the affected scheduler/inbox/lifecycle tests,
  full local suite with isolated PostgreSQL, Ruff/mypy and exact-head hosted checks.
  Retain the original failing regression and any later failures separately.

These are synthetic software checks, not fresh market evidence, economic advantage,
CP7 qualification or a new performance/soak measurement. Installed application,
accounts, data and external storage remain untouched. No rollout is authorized.

## Observed correction

The new controller regression failed against unchanged source `16c6128`: six
ordinary passes produced no independent trial despite thirteen free slots. Its
original failure receipt is retained separately. No installed reproduction was run.

Eligible queued work still dispatches first. When only future deferred jobs remain,
the controller checks bounded inbox capacity and the existing gates, then attempts
its real deterministic generator. A valid independent proposal follows the normal
evaluation, sole-writer reservation and paired funding path. Only when discovery
cannot proceed does the deferred retry choose the next sleep. Submission rechecks
the same four-job bound inside its existing registry transaction, preserving safety
when another producer wins the final slot after discovery's capacity check.

Seven new regressions cover controller-generated discovery, frozen parent/backoff
and controller/registry reopen, a full deferred queue without new bundle issuance,
two producers contending for the last inbox slot, and resource/hourly/daily/pause
guards. The existing manual-queue test separately exercises capacity release and
later retry admission. The 54 affected audit/lifecycle/safety checks pass with
isolated PostgreSQL 17; Ruff and strict mypy (72 source files) also pass.

The complete local suite passes **546 tests, zero skips, one existing test-client
warning in 156.60 seconds**. The affected set passes 54 tests in 40.98 seconds.
[Scoped checks and raw/source hashes](f3-discovery-checks.json) retain the original
1.57-second failing case separately. Exact-head hosted results belong to PR24 and
issue #1. Earlier browser, USB load and soak measurements were not repeated for
this scheduler-only follow-up and retain their original source scopes.
