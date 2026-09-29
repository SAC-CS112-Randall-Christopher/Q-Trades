# Learning assessment and recommended next development

This is an assessment and proposal, not an implemented strategy change. Runtime
status was inspected at 20:57 Denver on September 27, 2026. No trading parameters,
account balances, risk limits, data subscriptions or running processes were changed.

Chris subsequently chose crypto spot as the first development focus and welcomed
LLM involvement. The [crypto learning plan](2026-09-27-crypto-learning-plan.md)
supersedes the development priorities below, including the options feasibility work.
This document retains the original audit evidence and description of current code.

## Main finding

The application currently performs bounded strategy selection. It does not train a
predictive model, invent strategies, identify causes of losses, or rewrite itself.
It can perform its programmed reviews without ChatGPT. A stronger research loop
needs useful labeled observations, realistic execution, controlled experiments and
independent evidence that a proposed change improves future results.

## Current evidence

[Status receipt](../evidence/learning-audit-2026-09-27.json) records the following.
These are application-reported observations; this audit did not independently query
the database journal or refresh every external provider entitlement.

| Item | Observed state |
|---|---|
| Spot primary | $99.7593799833 equity from $100 funding; two completed trades, zero winners; $0.1990161167 modeled fees; no replenishment or successful attempt. |
| Spot review | Zero completed scheduled reviews or promotions. First due 21:05:18 Denver; it was not yet due at inspection. |
| Options primary | $100 equity; 59 AAPL historical sessions through August 12, 2026; 5,072 contract observations; zero trades, reviews or promotions. |
| Options data | Application's 60-request UTC-day budget exhausted; collection waits until UTC midnight. First review due 23:52:25 Denver. |
| Options exclusions | 985 spread/quote, 475 size, 416 volume/open-interest and 89 premium/cash-budget rejections. Counts are evaluations, not independent contracts or counterfactual profitable trades. |
| Feed | BTC/ETH used actual Binance.US REST fallback; inspected stream book/trade counts were zero. Requested 100 ms streams are not evidence of received push data. |
| Accounting | Both application reconciliation reports were balanced with no projection errors. |
| Resources | Short application sample reported 2.55% average machine CPU and 32 ms engine p95; not a sustained capacity guarantee. |
| AI | Disabled, $0 daily model budget. |

These data cannot establish a profitable strategy, successful learning, or the
majority-$100-to-$1,000 target. Thousands of price observations are not thousands of
independent investment outcomes. Two losing spot trades also do not establish that
the strategy cannot work or that any particular parameter caused the loss.

## What the current loop actually does

- `paper_strategy.py` defines three frozen breakout variants. They differ in
  lookback and volume threshold; the controller does not discover new values.
- `paper_engine.py:review` compares their separate portfolios in two disjoint
  four-hour windows. Each candidate and incumbent needs ten fully contained trades
  in each window, positive stressed candidate P&L, a mean-return improvement and
  an acceptable relative drawdown. Switching also requires eight hours since the
  last promotion and a flat primary account. These are heuristics, not a formal
  confidence calculation or a guarantee of generalization.
- `options_policy.py` defines two frozen daily-momentum policies. The options review
  compares two 20-session historical windows with similar trade-count, cost and
  drawdown gates. Replay advances chronologically; it is not live paper trading.
- Both failure paths preserve losses and funding before a below-$5 top-up. Their
  response is predetermined: use the selective policy and apply a cooldown. They
  record observed facts but do not run causal diagnosis or validate a repair.
- Risk reviews can reset the current risk peak and resume after a cooldown, while
  retaining lifetime drawdown. That is programmed containment, not evidence that
  the reason for losses has been resolved.

The options risk budget is an immediate feasibility issue: 2.5% of $100 is $2.50
for the entire premium plus both fee sides. With the current $0.50/side fee model,
only $1.50 remains for the premium. No observed candidate passed all requirements.
More frequent reviews cannot fix that constraint. A future IBKR-specific fee model
would need its own version; the current fee assumption is not IBKR's fee schedule.

Seven existing focused tests passed for review timing, disjoint-window promotion,
below-$5 replenishment ordering and risk cooldowns. One upstream Starlette warning
remains. Those tests validate mechanics with fixtures, not statistical validity or
actual successful adaptation. The full suite was not rerun for this documentation audit.

## Recommended approach

### 1. Make evidence and affordability reliable

Resolve push-feed connectivity and verify actual quote/event age before studying
fast execution. Obtain an authorized options API under the user's free-data
constraint before evaluating intraday options. Continue labeling historical and
delayed experiments separately. Do not change providers or buy subscriptions here.

Add a capital-feasibility report showing which contracts satisfy full-premium risk,
cash, costs, liquidity and expiry requirements, and how much capital a qualifying
contract would require at the existing risk fraction. Do not loosen filters merely
to produce activity. Report when the proposed strategy is infeasible at $100.

### 2. Learn from market opportunities as well as completed trades

Persist compact, versioned decision records: features known at decision time,
source and receipt times, quoted prices/sizes, eligibility/rejection reasons,
strategy version and a future outcome that becomes available only after its horizon
has elapsed. Track missing labels and delistings rather than silently dropping them.

A separate signal-research track can study qualifying and rejected opportunities
without spending fictional capital. Its hypothetical returns must never be counted
as fills, independent account successes or proof that unaffordable trades were
possible. Options labels must reflect the option contract itself; stock direction
alone cannot establish option profitability.

Retain these compact observations and trade evidence locally. Bound raw tick
retention, report coverage and storage growth, and verify backup/restore. Collecting
the entire market at maximum frequency is not a prerequisite for useful learning.

### 3. Add an experiment system before more complex models

Start with a small set of explicit hypotheses and parameter ranges. For example,
test whether a cost/liquidity filter improves net outcomes relative to the same
strategy without it. Keep all attempts, including rejected candidates, in a registry.
Use cash and a suitable passive exposure as baselines with comparable accounting.

Fit using past data, validate chronologically with gaps for overlapping outcomes,
and then freeze the candidate for observation on later data. Never repeatedly tune
against the same final evaluation period. Account for correlation and multiple
comparisons when assessing uncertainty. The existing ten-trade gates are not
sufficient proof merely because they pass.

An initial predictive model could estimate whether a future move is likely to cover
spread, fees and modeled slippage, or rank which opportunities merit further study.
Begin with an interpretable statistical baseline and compare a more flexible model
only if it adds measurable value. Unrestricted reinforcement learning is premature
while execution and reward realism are still being established.

### 4. Promote only after new evidence

Run a frozen candidate and incumbent on the same prospective observations in
separate portfolios. Evaluate net return, drawdown, exposure, turnover, cost stress,
available trade count and different market conditions. A larger number of correlated
trades is not a substitute for independent evidence. Promotion should require new
matured evidence since the previous decision and a predeclared improvement criterion.

Keep the last accepted version available for controlled rollback; preserve all
history. Add explicit deterioration monitoring, rollback criteria and exception
reports. A candidate must not change capital limits, fee assumptions or the scoring
definition to make itself look better. Reassess automatic recovery from risk pauses
as part of that design rather than calling elapsed cooldown time a learned fix.

### 5. Keep four-hour reviews, separate them from changes

Each review should state: new evidence collected, opportunities and trades, costs,
data gaps, candidate comparisons, uncertainty, the action taken and the next
falsifiable experiment. "No change: insufficient evidence" is a valid result.
Waiting for more data must not lead to repeating an old window as new evidence.

Deeper research should be triggered by sufficient new outcomes, persistent
deterioration, a data/execution defect or an account failure. A periodic engineering
review can check hypotheses and experiment design; no person needs to manually tune
every four hours. On failure, distinguish data faults, simulation faults, cost drag,
risk concentration, changing market behavior and an unproven signal. Explanations
remain hypotheses until tested on subsequent evidence.

### Responsibilities and objective

| Work | Owner in the recommended design |
|---|---|
| Ingestion, labels, tests, paper trades, accounting, scheduled reports | Deterministic local application |
| Fit and compare bounded statistical candidates | Automated experiment runner; proposed, not implemented |
| Suggest hypotheses and explain evidence | Optional human/LLM research review; model calls remain disabled |
| Review new features, model classes and execution assumptions | Development review before admission to the candidate bank |
| Risk permissions, subscriptions and real trading | Existing explicit authorization boundaries |

Keep the requested majority-$100-to-$1,000 benchmark, but define an evaluation
horizon before making repeatability claims. Track failures, open/censored attempts,
time to target, drawdown and every top-up. Do not count correlated shadows or repeated
crossings as independent wins. Early milestones should be realistic fills and a
repeatable positive net result; a learning algorithm cannot promise a 900% return.

The next bounded implementation should be the learning evidence report and labeled
opportunity dataset, accompanied by feed and capital-feasibility diagnostics. It
would make clear what has been learned and why the controller changed or abstained.
New model complexity can then be evaluated against that foundation.

## Research supporting the recommendations

- [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf): testing many strategies on the same history creates selection bias; a nominal holdout alone does not resolve repeated searching.
- [Bailey and Lopez de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf): evaluation needs to consider sample length, non-normal returns and the number/dependence of trials. These statistics are not currently implemented here.
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): chronological splitting avoids training on future observations; it does not automatically solve overlapping labels or multiple testing.
- [Alpaca's documented paper/live differences](https://docs.alpaca.markets/us/docs/paper-trading): concrete examples of omitted impact, queue position and latency effects. This is supporting context, not a claim that our simulator uses Alpaca's fill model.
