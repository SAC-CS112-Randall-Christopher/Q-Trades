# Original account redesign — source proposal for #66

Chris requested redesign after poor original-account win rates. This lane starts
from installed/main `d36a45a7bee7c79e02cb06ad4fee112b330f5c07`. It adds eight fixed
entry mechanisms, prospective original-account selection, and an explicit v4 Lab
contract. It does not install, select operating rules, or execute a model.

## What the retained observations establish

One supported read on October 6, 2026 at approximately 20:03 MDT found:

| Original account | Closed trades | Net wins | Net win rate | Net trading P/L | Fees |
| --- | ---: | ---: | ---: | ---: | ---: |
| primary | 191 | 3 | 1.57% | -$19.88 | $16.70 |
| breakout-v1 | 191 | 3 | 1.57% | -$19.88 | $16.70 |
| responsive-v1 | 206 | 2 | 0.97% | -$21.58 | $17.88 |
| selective-v1 | 149 | 4 | 2.68% | -$15.93 | $13.24 |
| universe-control-v1 | 189 | 3 | 1.59% | -$19.68 | $16.54 |
| universe-wide-v1 | 208 | 5 | 2.40% | -$22.33 | $17.76 |

Combined: 1,134 closed records, 20 net wins, net loss $119.2796487794 and fees
$98.8296197794. These accounts share markets and closely related rules. The
record count is not a count of independent trials. Fees are observed accounting
components; subtracting them does not reconstruct a frictionless counterfactual.

Primary's latest 100 closes had median holding time 47.11 seconds: 55 under one
minute, 90 under five minutes, 74 ATR stops, 23 trailing stops and three progress
exits. Twenty-two had positive net-plus-fees; only three were positive after
fees. The other five samples also had mostly very short stop exits. Pagination
reported older records; the latest-100 samples are incomplete historical coverage.

The remaining original pair, trial `lab-cf5f5ccb9b581732e136c5fc`, is a frozen
long-horizon range-versus-breakout comparison. Both had zero closes and zero fees
at this observation. They are low-information accounts, not demonstrated losers.
Its original seven-day review and controls must remain identifiable.

## Concrete prospective allocation

| Account | Proposed mechanism | Question it tests |
| --- | --- | --- |
| primary | cost-breakout-v1 | Does confirmed trend/volume with bounded entry extension reduce weak breakouts? |
| breakout-v1 | breakout-retest-v1 | Does waiting for a complete-bar retest reduce chasing? |
| responsive-v1 | trend-pullback-v1 | Does recovery from a moving average work better than buying the range high? |
| selective-v1 | vwap-reclaim-v1 | Does reclaiming the preceding hour's volume-weighted price improve entries? |
| universe-control-v1 | range-fade-v1 | Do flat-trend lower-range reversals offer useful contrast with trend entries? |
| universe-wide-v1 | momentum-followthrough-v1 | Does sustained bullish follow-through with higher lows help? |
| New replacement Lab candidate | compression-breakout-v1 | Does a volume-backed escape from a compressed range preserve value? |
| New replacement Lab reference | washout-rebound-v1 | Does higher-low recovery after a high-volume washout preserve value? |

The six existing account identities, symbol memberships and actual losses stay.
Changing their rule needs flat positions, no pending orders, healthy observations,
and matching strategy/control versions. Earlier evidence keeps its original
version. An economics window spanning a switch is excluded from rankings;
completed windows and lifetime counters remain. The Primary operator choice is
not automatically replaced by the legacy variant promoter.

The two existing Lab accounts cannot be rewritten. A separate authorization
would retire/drain/archive their old trial through its existing owner and create
the distinct v4 pair. Their retained funds/history are not transferred or reset.
The new pair uses the existing $100-per-account fake funding policy and a fixed
one-day minimum review, with complete five-minute inputs, six-hour maximum hold
and two-hour progress check. The currently installed horizon policy must be read
and explicitly reconciled for medium-horizon admission; the source proposal does
not amend it. Twenty-slot capacity includes protected accounts and reservations.

## Executing and financial boundaries

Each new method consumes at most 600 causal minute observations, requires 305
contiguous closed minutes and 60 complete UTC five-minute bars, and rejects gaps,
bad prices, zero volumes and stale inputs. Exact fixed predicates are implemented
in `src/trading/redesign_strategy.py`; the source digest binds captured/replayed
evidence. The prior range and median-volume window is 20 five-minute bars, with
14-period Wilder ATR and 20-period EMA where applicable. These are hypotheses,
not fitted forecasts. Tests with constructed inputs demonstrate rule semantics.

Entries compare 1.5 ATR with actual configured round-trip fees/slippage and the
current executable spread. This is a volatility scale check, not expected profit.
Per-account cost annotations do not mutate another account's feature evidence.
Sizing, cash-only constraints, 2.5% entry and 5% aggregate risk ceilings, loss
stops, funding policy, fee profiles and book precision remain with their existing
owners. Protective stops can act immediately; a longer maximum hold is not a
mandatory minimum hold. Observed fills remain subject to the existing simulation
limits, so paper success would not establish a live trading edge.

Startup and rule selection require a subsequent complete five-minute observation.
The new timing applies only to the marked bank/v4 methods. Existing v2/v3 rules,
their literal serialized contracts, and their prior stale-feature behavior remain.
V4 explicitly labels unused lookback/volume compatibility fields inapplicable.
Its executed input prefix, calculation cutoff and later freshness check are
retained. Missing or altered evidence is unmatched; historical missing new-source
fields remain compatible only where the historical method does not require them.

## Normal account workflow and recovery

Accounts → inspect an original account → “Choose this account's next strategy”.
No strategy is preselected. One explicit action saves its exact request before
posting. Same-origin Web Locks coordinate all saves and compare-and-clear
operations across windows. Unsupported coordination refuses a new change.

The existing financial transaction appends a permanent zero-money strategy-change
receipt. Duplicate exact requests reopen that receipt even after a later control.
Conflicting account/payload reuse is refused. A lost acknowledgment stays saved;
“Reopen saved strategy result” reads its exact receipt without another POST.
Clearing requires a verified receipt and refreshed account control version.
Known precommit refusals keep their reason and require refreshed status and a new
deliberate action. No automatic retry, account reset or hidden funding follows.

## Verification and remaining acceptance

See `ORIGINAL_ACCOUNT_REDESIGN_VERIFICATION.md` for executed checks, retained
failures and the actual disposable native/dashboard results. Source proof is
separate from operating selection and forward-market performance.

Additional operating approval must identify the reviewed PR head and resulting
merge target, permit the supported ExpectedCommit updater and a bounded restart
of the verified existing paper-service owner, and authorize the six prospective
flat-account switches plus the old pair's retirement/new distinct v4 pair and
necessary explicit medium-horizon policy declaration. Reuse existing preservation
and updater owners. Do not install unrelated draft PR74/75/76 or repeat the
already accepted rollout to pursue other observations.

The ten newly funded exploratory accounts remain separate and are not replaced
by this proposal. Direct NAT/writer association remains unproven. Populated
Library/Review acceptance and packaged Windows desktop #65 remain unproven and
are not prerequisites. The retained researcher pilot remains paused; this source
work does not authorize another model request, holdout, external review, paid
call, training, download, compression, scheduler, backend or promotion.
