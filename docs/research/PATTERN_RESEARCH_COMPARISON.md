# Saved finding to a fixed research comparison

This is a bounded source proposal in the existing daily-analyzer lane. The
product prepares a reviewable comparison; it does not submit an experiment,
dispatch a model, fund an account or activate a research policy. Literature
priorities and their limits are in
[`DAILY_PATTERN_ANALYSIS.md`](DAILY_PATTERN_ANALYSIS.md).

## First supported mapping

Accept one immutable saved **BTCUSD native 5m** `resistance_breakout` or
`breakout_retest` finding as the motivation for an independent comparison:

| Fixed field | Candidate | Reference |
| --- | --- | --- |
| Rule version | `reviewed-lab-rules-v4` | `reviewed-lab-rules-v4` |
| Family | `breakout-retest-v1` | `cost-breakout-v1` |
| Symbol / holding horizon | `BTCUSD` / `medium` | `BTCUSD` / `medium` |
| Input version / stop ATR | `closed-minute-bars-v1` / `1.5` | `closed-minute-bars-v1` / `1.5` |
| Maximum hold / progress checkpoint | 21,600 seconds / 7,200 seconds | 21,600 seconds / 7,200 seconds |
| Minimum outcome review horizon | 86,400 seconds | 86,400 seconds |

These are existing RuleSpec defaults and fixed bank algorithms, not newly tuned
parameters. Serialized v4 `lookback=10` and `volume_multiple='2'` are compatibility
fields; the v4 contract marks them inapplicable as common adjustable entry
controls. Exact full RuleSpec, proposal and implementation identities must be
retained. Older v2/v3 contracts and consumed attempts remain unchanged.

The scanner recognizes a crossing or separate return at a previously confirmed
pivot zone. The bank retest method uses the preceding twenty-bar range and the
immediately preceding breakout bar, with fixed EMA20, ATR and volume predicates.
The breakout reference uses its own rolling-range, trend, extension and volume
predicates. These algorithms differ. A scanner finding motivates testing the
fixed methods; it neither proves their entry condition nor replaces it.
See [`candle_patterns.py`](../../src/trading/candle_patterns.py) and
[`redesign_strategy.py`](../../src/trading/redesign_strategy.py).

There is no exact support-bounce RuleSpec in this slice. Other symbols, native
frames and pattern kinds require explicit unsupported/refused results. Do not
translate a 4h event into a 5m event, substitute BTCUSD for another market, or
label range-fade, washout-rebound or VWAP-reclaim as the same detector.

## Prepare through existing evidence and evaluation owners

1. Resolve the requested saved daily assessment and its finding membership.
   Reopen the exact immutable campaign/symbol/timeframe event, associated level
   and archived native source references. Verify their hashes, row identity,
   causal cutoff and gaps. The mutable latest-event index is not the historical
   authority. Later scanner progress can invalidate a captured chart bookmark
   without changing the original event; preserve that distinction.
2. Issue a bounded immutable bundle in the existing registry's Lab bundle store.
   Keep the original finding, interpretation and limitations separate
   from the current executable-input summary. Existing prospective/holdout
   exposure exclusions remain authoritative. A caller-supplied finding body or
   an old chart picture cannot stand in for verified server evidence.
3. Construct one fixed `LabProposal` with a stable request UUID, the exact issued
   bundle digest, `source='deterministic'` and `kind='independent'`. Preserve the
   hypothesis and a falsification criterion: a later eligible matched trial
   would need better after-cost outcomes than the reference and existing passive
   and cash comparisons; a descriptive retest count is insufficient.
4. Call the existing `AutonomousLab.evaluate` with actual current deterministic
   inputs, or retain its explicit unavailable/wait/refusal. Reopen preparation
   by the same request identity without silently reevaluating or resubmitting
   it. The prepared result retains its observation time and expiry; a later
   current evaluation is a distinct observation.

The v4 evaluator uses up to 600 retained public minute bars, requiring at least
305 contiguous causal closed minutes and sixty complete UTC five-minute groups,
plus a fresh executable book under the current policy. Its minute-derived bank
input and source digest are separate from the saved native 5m scanner archive.
No archive replay or old finding is a substitute for these current inputs.
The existing evaluation reports a supported exploratory configuration with
`financial_authority=false`, `profit_required=false` and a ninety-second expiry;
it is not an order, forecast, backtest or permission to trade.
See [`autonomous_spec.py`](../../src/trading/autonomous_spec.py),
[`autonomous_lab.py`](../../src/trading/autonomous_lab.py) and
[`lab_proposals.py`](../../src/trading/lab_proposals.py).

## Normal UI workflow

1. In the daily analyzer, choose an eligible saved BTCUSD/native-5m breakout or
   retest with recorded volume confirmation, then select **Review prospective
   comparison**. This reads the exact saved source with GET; it does not prepare
   or submit anything. Review the original reason, native source hashes and
   captured five-frame coverage, including missing or incomplete frames.
2. Select **Prepare fixed comparison** explicitly. The UI retains one UUID and
   its exact finding digest before sending the preparation. The result shows
   either **Preparation supported by the captured numerical check** or
   **Preparation waiting**, with the original observation, numerical evidence
   and expiry. This is a preparation-time check, not current executable
   readiness or a trading result. Nothing reaches the Lab inbox, a model or an
   account through this panel.
3. If acknowledgment is lost, keep the original UUID and select **Find original
   preparation result**. Recovery uses only the exact request GET. Do not resend
   the POST or replace the pending UUID; a missing read is not proof that an
   uncertain preparation cannot still commit.
4. Open **Saved immutable preparations** and select **Read saved preparations**.
   Each page contains at most twenty rows, ordered by stable descending request
   identity, not preparation chronology. **Next preparation page** continues
   that cursor. Select **Reopen preparation** for the desired UUID to read its
   exact original result; this server history works without a browser-local
   receipt hint. Unavailable history is reported rather than treated as an empty
   successful list.
5. An original wait stays frozen. **Review a separate current observation**
   performs a fresh source GET and leaves the earlier wait in history. Only
   another explicit **Prepare fixed comparison** records a separate new UUID.
   There is no automatic retry, wait-to-supported upgrade or search for a
   preferred result. **Return to original daily finding** keeps the preparation
   connected to the saved evidence that motivated it.

The panel has no experiment-submission or activation control. A future authorized
submission is a separate action through the existing Lab workflow and must pass
its current gates. The UI implementation is in
[`PatternComparisonPanel.tsx`](../../apps/web/src/PatternComparisonPanel.tsx);
exact source, preparation and history recovery are handled by
[`pattern_comparisons.py`](../../src/trading/pattern_comparisons.py).

## Evidence and authority that preparation does not supply

Product preparation stops before inbox submission. A separately identified
disposable fixture may submit the prepared proposal through the existing
controller to prove numerical/inbox compatibility. That software proof is not a
prospective operating comparison or an authorization to reserve or fund accounts.
Any later operating submission retains normal policy, equivalent-rule rejection,
capacity, family quotas, resource guards, execution costs and financial owners.
A new finding UUID cannot bypass a previously attempted equivalent rule.

Six hours is the maximum position hold, not outcome maturity. A later funded
medium trial has a minimum twenty-four-hour review horizon, potentially longer
under the frozen Lab policy. Missing executable coverage, no exposure, losses
and adverse results remain reportable outcomes; no useful result is guaranteed.

This prepare-only slice leaves existing model packets, profiles, grants and
selection policy unchanged. Giving an AI the new finding or v4 capability needs
separate reviewed evidence/catalog and model-authority integration. Preparation
alone is not autonomous learning, measured model quality, after-cost strategy
improvement or an activation decision.
