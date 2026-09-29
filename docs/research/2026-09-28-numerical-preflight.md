# First real quote-model preflight

September 28, 2026, 05:38 Denver. This manually initiated, predeclared implementation
check exercised the registered numerical tool on recorded public BTCUSD quotes.
It was separate from model qualification and did not use an LLM proposal.

The fixed `quote-ridge-v1` experiment used five-minute momentum to predict a
five-minute subsequent quote return after the existing cost hurdle. Configuration,
source hash and observation cutoff were recorded before querying the data.
There was no feature, horizon or parameter search.

The read-only database snapshot contained 674 quote-minute events, with no older-row
truncation. The builder retained 634 matured examples, excluding 5 warmup, 7 label-gap,
25 feature-gap and 3 unmatured records. The chronological split and purge left 431
training and 191 test examples. Preprocessing and the fitted coefficients used only
training data. Labels use later quotes, 0.10% fees per side and 2 basis points of
adverse slippage per side; these are the registered research assumptions, not a
claim about actual exchange fills or today's exact account fee tier.

| Measured result | Value |
|---|---:|
| Test forecast MSE, basis points squared | 105.14125772 |
| Constant training-mean baseline MSE | 108.73830186 |
| Relative MSE reduction | 3.307983% |
| Positive-after-cost predictions | 0 |
| Eligible for forward review | **No** |

The small forecast-error reduction does not establish a profitable strategy or
statistical reliability. There were no positive predictions after the cost hurdle.
The short history and overlapping labels limit independent evidence. These are
observed quote labels, not simulated fills, account returns or $100-to-$1,000 attempts.
The primary account, strategies, funding and risk permissions were not changed.

The same retained snapshot reproduced the result exactly. That is a reproducibility
check, not another validation sample. Passing the consumed test end back into the
tool returned `insufficient_data`, requiring at least 50 fresh purged test examples.

**Before enabling a research journal or harness, import this consumed test boundary:
1790595239.9180105.** Do not silently initialize its prior-test boundary to zero and
select a different feature on these already examined final-test observations.
Further overlapping comparisons would be exploratory development and need a later
untouched evaluation period before any forward-review claim.

Receipts in `docs/evidence`:

- `numeric-preflight-freeze-20260928T113855Z.json`: predeclared experiment and cutoff.
- `numeric-preflight-20260928T113855Z.quotes.json`: retained public observations and manifest.
- `numeric-preflight-20260928T113855Z.json`: fitted parameters, metrics, exclusions and hashes.
- `numeric-preflight-validation-20260928T113855Z.json`: identical replay and reuse refusal.

No numerical model or LLM was installed into the trading decision path by this check.
