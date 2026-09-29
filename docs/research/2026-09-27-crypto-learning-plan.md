# Crypto learning: first development focus

September 27, 2026. This is a proposed implementation specification, not a claim
that trained models or LLM research are running. Chris selected crypto spot as the
first focus, welcomes aggressive paper experiments, and wants actual learning
beyond selection among fixed strategies. LLM involvement is welcome; its provider,
credentials and spending cap remain open. Local operation and the $100 fake-money
objective remain in force. Stocks/options expansion is deferred, with history retained.

The subsequent [agent-harness design and local model evaluation](2026-09-27-agent-harness.md)
specifies research, training, review and operations roles. Chris authorized testing
already installed models on these tasks. This is distinct from enabling the harness
inside the running trading worker.

## Why this focus fits

Cash-funded crypto spot supports fractional quantities and continuous markets without
option expiry, time decay or margin liquidation. Orders still need to satisfy each
pair's quantity increments and minimum notional. It is operationally simpler than
small-account options, but large losses remain possible. More volatility does not
establish more predictable returns, and long-only spot cannot profit directly from
every downward move; cash is a valid position.

Binance.US permits trading during an ACH withdrawal hold. That is distinct from
securities cash-account settlement, and also distinct from immediately withdrawable
funds. The application continues to model funded cash, not provisional bank credit.
See [Binance.US's hold explanation](https://support.binance.us/en/articles/9842927-why-can-t-i-withdraw).

The objective is profitable use of liquid opportunities after all costs. Market
trading volume is useful liquidity evidence; the application's trade count is an
outcome, not a quota. Frequent trading requires enough expected movement to overcome
spread, fees, slippage and adverse fills. A fast quote feed also improves observation
without implying that a home computer can win exchange-latency races.

## Current gaps that affect the research

- The current learner selects predefined breakout variants. It does not fit a model
  or discover features. Its failure response is a programmed policy switch/cooldown.
- Actual Binance.US REST data is available. At the learning audit, received WebSocket
  book/trade counts were zero. Reliable push reception and measured event age are
  prerequisites for claims about order-flow or subsecond advantages.
- The simulator charges 0.10% per side. Binance.US currently publishes 0% maker and
  0.02% taker on most spot pairs, with a different BNB/USD tier. Introduce a versioned
  current-rate scenario and retain the existing assumption as a cost stress scenario.
  Do not rewrite old fees or compare candidate/incumbent results under different
  costs as if that difference were learned improvement. Resting limit orders cannot
  be awarded free maker fills merely because the quoted price was touched.
- The first audit had only two completed primary trades. That is insufficient
  evidence for strategy skill, a cause of failure, or the majority-10x objective.

At 21:09 Denver the first scheduled spot review had completed and retained the
existing policy for insufficient forward evidence/no passing challenger. Primary
equity was still $99.7593799833, with two closed trades and no replenishment.
See the [read-only follow-up receipt](../evidence/crypto-focus-audit-2026-09-27.json).

Fee source: [Binance.US published schedule](https://www.binance.us/fees), checked
September 27. Account-specific commissions and fees paid in another asset remain
separate matters to verify before any eventual live integration.

## The learning system to build

1. **Observe opportunities with their actual information times.** Store compact
   feature snapshots for a screened, liquid USD-quoted universe, including skipped
   opportunities. Begin with returns, realized volatility, relative volume, spread,
   executable depth and cross-asset relationships. Add signed trade flow only after
   its stream works. Attach available futures funding/open-interest/basis context
   with source, units and age; it remains observation-only. Missing features remain
   missing, and later revisions cannot leak into earlier decisions.
2. **Create outcomes after their horizons mature.** Candidate horizons are 1, 5,
   15 and 60 minutes, subject to experiment registration. Label forward executable
   return after costs and adverse excursion; distinguish a research label from an
   actual simulated fill. Include rejected signals and data gaps so the model does
   not learn only from cherry-picked completed trades. An unavailable future quote
   is an unavailable label, not a zero loss or a profitable exit.
3. **Train models that generalize across setups.** Start with a calibrated statistical
   baseline and a nonlinear tree model for net-return/risk estimation and opportunity
   ranking. Training should learn relationships and feature interactions rather than
   simply pick a named strategy. Compare additional model classes, regimes and online
   updates through experiments; complexity must earn its place on later observations.
4. **Use an LLM as a researcher and critic.** Give it compact evidence about failures,
   prediction errors, costs and market conditions. It can propose new features,
   relationships, horizons and models, specify a falsifiable experiment, and critique
   the findings. Generated research code runs in an isolated, resource-limited process
   against read-only data, without execution credentials or financial-state writes.
   Model-generated explanations are hypotheses until tested. Hosted/local inference
   should use a replaceable adapter and a hard budget; this plan does not select a
   provider or infer a paid budget from Chris's willingness to use an LLM.
5. **Test, then run frozen candidates prospectively.** Register every search and
   failed experiment. Separate past training, validation and later testing; purge
   overlapping outcome periods across splits. Account for repeated searches and
   correlated observations. Compare with cash, appropriate passive exposure and the
   existing rule baseline, all under identical fees and fill assumptions. A candidate
   must also earn its place in a separate forward paper account. Promotion, monitoring
   and rollback are versioned actions that preserve prior evidence.

Execution remains deterministic: a trained model supplies scores and uncertainty;
the application translates them into orders within a declared cash/risk profile.
An LLM does not manage the ledger, issue arbitrary orders or change its own limits.
Neither ChatGPT nor an LLM request needs to remain available for position management.

This architecture is informed by [Microsoft Qlib](https://github.com/microsoft/qlib),
which exposes dataset/training/evaluation workflows, and
[R&D-Agent-Quant](https://arxiv.org/abs/2505.15155), which connects hypothesis creation,
implementation and experimental feedback. These are architecture references, not
installed dependencies or evidence that their reported results transfer to our
crypto venue, capital, costs or hardware. No framework has been installed by this audit.

## Aggressive paper exploration and the four-hour loop

Paper research should explore wider entry, exit, holding-period, concentration and
position-size choices. Each risk profile must be declared before evaluation and
identified separately from the prediction model. The exact new profiles have not
yet been implemented. Keep existing baselines so aggressive choices can be compared
fairly, and preserve all failed $100 attempts and every below-$5 replenishment.

Every four hours, the application should summarize newly matured outcomes, compare
predictions with results, identify possible model/data/execution failures, and choose
the next registered experiment. Fit a new version only when enough new evidence has
arrived. No change is an informative result when the previous window contains no
new data. New hypotheses may require an LLM; model fitting and numerical scoring
can run locally without inference charges or manual parameter tuning every four hours.

On an account failure, preserve a reproducible evidence packet, classify the
observed failure, propose a testable correction, and compare it against the prior
version. Replenishment does not certify that the correction worked. The below-$5,
flat/settled/reconciled replenishment policy and cumulative funding/loss record remain.

The requested target is $100 reaching $1,000 in most attempts. Define a fixed time
horizon before scoring that claim; include failed and unfinished attempts, total
funding, time to target, costs and drawdowns. Correlated shadow accounts are not
independent successful attempts. Model complexity and frequent retraining do not
guarantee a 900% return.

## Data budget and local resources

The existing 60-request UTC-day cap belongs to the historical options collector.
It does not cap the crypto market feed. Binance.US's public BTCUSD exchangeInfo
response on September 27 reported 6,000 request-weight units/minute and 300,000 raw
requests/5 minutes. Its separate order limits do not describe data requests. These
are current ceilings, not target collection rates or a daily allocation to spend.
Read updated exchangeInfo and usage headers; honor 429/Retry-After and backoff.

Streaming market events are distinct from the WebSocket request/response API.
The stream documentation limits client control/ping/pong traffic to 5 messages/sec
and 1,024 subscriptions per connection; that is not a five-price-update/sec cap.
See [Binance.US API documentation](https://docs.binance.us/). Reuse collected events
across all candidate models rather than issuing duplicate per-model subscriptions.

Keep the existing local financial journal. Store compact feature/outcome records
with a bounded ingestion queue, batched writes and measured growth. Raw depth/tick
capture remains separately bounded; retain the evidence required to reproduce a
trade or experiment. Measure CPU, RAM, disk growth and event age under load before
increasing subscriptions. Optional training yields resources to execution.

For completeness, Market Data's authenticated Free Forever plan advertises 100
daily credits with a 9:30 a.m. Eastern reset. Credits may depend on symbols returned;
they are not universally interchangeable with HTTP request counts. The documented
plan is distinct from our anonymous historical AAPL demo access, whose daily server
allowance was not established. Sources: [plan limits](https://www.marketdata.app/docs/account/plan-limits/)
and [anonymous sample access](https://www.marketdata.app/docs/api/authentication/).
Options data expansion is deferred under the new crypto focus.

## First end-to-end implementation milestone

Deliver one crypto model experiment from observation to a visible result:

- Verify working push data or explicitly constrain the experiment to measured REST
  freshness; version the published-fee baseline separately from cost stress.
- Persist features and matured labels for eligible and skipped opportunities.
- Train and freeze a reproducible model; record dataset boundaries, feature/model
  versions, all search attempts, validation results and resource usage.
- Run it in a separate $100 paper portfolio against the current control under the
  same execution model. Do not immediately replace the primary policy.
- Show in the phone dashboard what was trained, what changed, new evidence, net
  results, uncertainty and why the four-hour review promoted or rejected a candidate.
- Add the LLM hypothesis/review interface to that evidence pipeline; activate model
  calls when provider access and a spending limit are configured.

Completion requires persisted results and recovery after restart, meaningful leakage
and accounting checks, and actual forward observations. A training script, a good
backtest or an LLM narrative alone does not establish a successful learning system.
