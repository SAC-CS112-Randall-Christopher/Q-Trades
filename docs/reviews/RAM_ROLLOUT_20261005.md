# Authorized capture, trained-v2 serving and RAM rollout — October 5, 2026 UTC

The human's "So lets find out" authorized the proposed merge/install/restart of
reviewed PRs #54–56 and execution of the already authorized single development
attempt when the unchanged full guard admits it. That rollout is complete.
The model attempt remains unused because actual admission stayed closed.

## Reviewed content and installed preservation

PR #54 merged as `177da494aa8912a2aaeb03fca3dcf15d5c5530c7`, #55 as
`e884e71533c57d5bd4e3583f3c5145e041a1c9bd`, and #56 as
`fa3accde7667404a7751f75a8d1b1cc6978a7808`. Main's full tree exactly matches
the reviewed #56 head `ef0e231da522416058b062c375945225a3beaf27`; no conflict
resolution or content substitution was needed. Both jobs at the same merged
head passed in [main run 37259390649](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/37259390649):
native 628 passed / 189 skipped, runtime-ownership 46 passed, and the dashboard
built 1,930 modules. Hosted skips do not replace the separate final-product
native PostgreSQL result: 1,026 passed / one existing skip in 526.86 seconds.

The existing updater applied the reviewed source and restarted the installed
paper task at main `fa3accde7667404a7751f75a8d1b1cc6978a7808`. All 218 checked
installed source/dashboard files match. Authenticated read-only before/after
queries prove exact preservation of all 1,208,535 original events and 12,802
journal lines; the journal remains balanced. All 247 protected configuration,
evidence, G: ownership and model-alias files match their original hashes.

The initial active-account equality check failed and is retained. It was
investigated rather than waived: two generated trial accounts retired through
normal `lab_trial_scored` / draining / archive / retirement events. Their archived
states match the appended archive events exactly; their original identity,
version, funding and starting-capital metadata are preserved. The eight remaining
accounts' same metadata is unchanged, and no new account was created. This is
an active-to-historical transition, with the original failure and reconciliation
receipts both preserved privately. Original accounts and successful parents
remain under their existing protection.

Normal installed navigation verifies financial activity, retained recording,
model readiness, trade account/status filters, older-page navigation and Journal.
Historical trial accounts remain in trade history. Storage reports recording
under the unchanged 400 decimal GB temporary / 100 GB retained policy. Startup
checked one owned segment with zero rollbacks; this rollout did not reproduce a
hot-journal crash in the installation. The real crash fixtures in #54 remain
the separate recovery proof. Existing capture gaps and pending retry bytes remain
visible; recording is not a claim of uninterrupted capture or an empty queue.

## Actual installed capacity, inference off

The bounded observation spans **818.712 seconds** from the first through the last
poll. There are **163 polls**: all **161 successful responses** report running,
fresh, error-free paper processing, with **two connection `ReadError` gaps**.
Those failed requests are retained as unknown observations; their root cause is
not established. The new server log contains only its startup informational
entries at the final inspection, and final health is fresh and balanced. The only observed blocking condition is
`engine_work_cooldown`; **zero polls admit research**. Trigger count advances
from 88 to 214. No memory, disk-space or capture-failure gate was identified
as the active refusal in successful status responses.

Deduplicating the retained latest-twenty windows yields **1,494 distinct reported
work samples**: median **58.594 ms**, p95 **109.454 ms**, maximum **634.495 ms**.
**115 exceed 100 ms**; none reach the one-second severe-stall boundary. The
bursts repeatedly renew the existing five-minute cooldown. These are reported
samples, not guaranteed complete coverage of every financial event.

| Measured stage | Median ms | p95 ms |
| --- | ---: | ---: |
| Complete transaction | 54.715 | 98.048 |
| Projection read/decode | 12.495 | 29.355 |
| Projection encode | 8.122 | 21.262 |
| Projection update | 20.722 | 38.764 |
| Database commit | 3.324 | 5.216 |
| Financial calculation | 0.781 | 2.709 |
| Writer lock wait | 0.002 | 0.004 |
| Periodic reconciliation | 47.878 | 64.936 |
| Periodic storage usage | 65.793 | 74.320 |

The stage populations differ and their percentiles are not additive. Occasional
writer waits reach 74.648 ms; read/decode, encoding and journal append also have
larger outliers in the retained receipt. This supports further investigation of
projection processing, database writes, scheduling and periodic maintenance;
it does not establish one root cause or justify raising a threshold. Average
process CPU at the final status observation is 8.79% of the whole machine;
that average does not measure spare capacity on the critical processing thread.

This is an ordinary installed observation, including navigation, read-only
preservation work and separately owned development preparation. It is not a
controlled installed off/on comparison. Two accounts retired and all reported
samples have `active_portfolios=false`; do not claim proof under active-position
load or infer a causal installed percentage gain. The balanced isolated RAM
benchmark remains separately described in [RAM_ASSISTED_CAPACITY.md](RAM_ASSISTED_CAPACITY.md).

## Real development question and refused dispatch

A temporary normal Q-Trades app runs with background workers disabled, a private
research registry and an authenticated financial observer with
`default_transaction_read_only=on` and no writer ownership. It is never attached
to financial mutation routes. Only its normal role-question POST is admitted.
Twenty-nine operating protection intervals are copied as boundary metadata;
no sealed plan/evaluation payload, training corpus or holdout is consumed.

One normal question is retained as
`role-3dc561bf69b31ba6fb55ed87f0ee3662`. Its question asks for a supported short
comparison against the reviewed breakout reference, or an offered dependency
wait if evidence is insufficient. The normal API freezes 600 actual retained
BTCUSD candles and a fresh actual existing public-venue book/instrument response.
The normal rendered research detail verifies `observed_public_market`, the two
reviewed capabilities and their calculated causal evidence. Both have no eligible
entry at capture. This is the application's evidence calculation, not a model
proposal or retrospective performance claim.

The normal packet is 3,470 bytes, or 6,071 bytes including the role prompt;
its SHA-256 is `a456cc36868ccd03e29a461dfe8330d3bed20d684cf1c6cebd9138f7013ced1b`.
Actual tokenized preflight remains an owned-child check when admission permits
dispatch; byte allowance alone does not prove token allowance. The originals and
rendered screenshot remain private.

Available RAM before the bounded admission check is **54.807 GiB**, above the
approved 24 GiB child ceiling plus 8 GiB free reserve. Actual backend preflight
checks the selected pinned base/adapter metadata and the full installed paper
guard for one cooldown window. All 29 checks refuse; the bounded run finishes
in **302.391 seconds** with **zero role attempts, zero allowances, zero model
children, zero proposals and zero paper trials**. The two status read errors
belong to the separate observation client; all development preflights record
the ordinary guard refusal. No trained-v2 inference or compatibility failure
was observed because no weights loaded and no answer was requested.

The temporary app and observer are stopped gracefully through their owned stop
request. Their private registry, exact original question/evidence, acknowledgment,
authorization, failed first setup and corrected setup are retained. The first
setup used `id` instead of the actual protection column `request_id`; it failed
closed before question creation and was corrected in the private harness only.
No model attempt was consumed by either setup. The installed paper task stays
running. Neither GIS nor an Ollama runtime is changed by this development path.

## Remaining acceptance and continuation

The RAM implementation and installed rollout are delivered; safe simultaneous
model work is still unproved. More available RAM alone does not remove the
observed timing refusal. Correct a measured remaining bottleneck or make a
separately explicit, tested resource-policy decision; preserve the full guard.
Do not repeat a long unchanged wait or create another question to hide this one.
The original authorized CPU float32/two-processor/600-second attempt remains
unused and requires no repeated approval when actual admission permits it.
Reopen the retained owned question and use the existing development dispatch
procedure with the installed source when the condition materially changes.

Actual trained-v2 loading/adapter activation, response/timing/peak-RAM evidence,
shutdown during inference and protected-work impact remain open. Current 4/4
development screening and 36-case qualification for both roles, operating
activation, genuine paper maturity/follow-up, CP23 sustained/usefulness work,
SEC native access and actual Crik connectivity remain distinct open stages under
issue #28. No qualification, trading benefit or operational feedback cycle is
claimed from this refused admission.

The redacted [installed receipt](ram-rollout-installed-checks.json) contains the
counts, distributions, exact identities and hashes of private originals. This
documentation does not change application/runtime behavior. New source delivery
or runtime policy changes retain their applicable approval boundaries.
