# Daily native-candle pattern analysis

Source research reviewed October 7, 2026. This document accompanies the daily
analyzer backend and normal Markets UI implementation in the existing scanner
lane. It defines the rationale and evidence boundaries; it does not activate an
operating policy, dispatch a model, authorize trading or establish an edge.

The requested workflow is hands-off daily analysis of eligible USD crypto
markets, with up to five next research priorities and five native charts per
market: 5m, 15m, 30m, 1h and 4h. Reuse the scanner's saved year preparation and
incremental closed-candle processing. A new day is a new immutable assessment,
not a reason to redownload a year or replace the original campaign and findings.

## What the primary evidence supports

Automatic recognition needs explicit numerical definitions. Lo, Mamaysky and
Wang formalized chart recognition and found incremental information in some
conditional return distributions for historical US daily stocks. Their result
does not validate these crypto markets, minute frames or after-cost execution.
[Author-hosted paper, 2000](https://www.mit.edu/~wangj/pap/LoMamayskyWang00.pdf)

Osler tested support/resistance published in advance by six FX firms against
minute-resolution prices and randomized comparison levels. Previously known
levels predicted some intraday interruptions, but relative strength assessments
were unreliable. This motivates causal level tracking rather than a claim that
more touches imply a known win probability in crypto.
[Federal Reserve Bank of New York, 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)

Crypto findings are mixed. Corbet and colleagues found stronger evidence for
variable moving-average rules than fixed crossover or range-break rules on
high-frequency Bitcoin. Their paper leaves liquidity and transaction costs for
further consideration; its carried-forward no-trading prices are not authority
to fabricate missing native candles here.
[Author manuscript](https://doras.dcu.ie/25053/1/The_effectiveness_of_technical_trading_rules_in_cryptocurrency_markets%5B1%5D.pdf)

Hudson and Urquhart found favorable historical technical-rule results, but their
selected Bitcoin rules had negative subsequent out-of-sample returns. Their
support/resistance family also had comparatively limited cost headroom.
[Published paper, 2019/2021](https://link.springer.com/article/10.1007/s10479-019-03357-1)

Deprez and Frömmel evaluated 75,360 rules, selected after transaction costs and
multiple-hypothesis adjustment, then assessed rule portfolios out of sample.
They report some improvement over buy-and-hold, especially in risk-adjusted
performance. This supports prospective, cost-aware evaluation; it does not make
an individual detected setup a verified profitable trade.
[Ghent University publication and manuscript, 2024](https://biblio.ugent.be/publication/01HY3C3S169G1N6QNYR55NZMFB)

Osler's order-level study supplies a possible explanation for both reversal at
known levels and continuation beyond them: take-profit and stop-loss orders
cluster differently in the sampled FX bank. It does not observe this project's
crypto order flow or test its retest and volume definitions.
[New York Fed staff report, 2001; published 2003](https://www.newyorkfed.org/research/staff_reports/sr125.html)

## Evidence strength and engineering priority

The primary sources were rechecked for this increment. There is no universal
best pattern or transferable standalone win rate. Known-level interruptions have
direct intraday FX evidence. Crypto moving-average, filter, volume and channel
rule studies offer broader, mixed evidence under different samples, costs and
selection procedures. Deprez and Frömmel report stronger results for OBV and,
to a lesser extent, moving-average and filter rules, with performance changing
by period and frequency. That is not evidence that our specific retest ranks
above those families.
[Accepted manuscript, conclusion and rule definitions](https://backoffice.biblio.ugent.be/download/01HY3C3S169G1N6QNYR55NZMFB/01HY60XZGZYHNQ6188MSVJT0SG)

| Research family | Evidence relevant to the family | Project priority and limit |
| --- | --- | --- |
| Known-level bounce / range reversion | Osler's advance-published FX levels support some intraday interruptions; this is not a test of a generic range-reversion rule. [Osler 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf) | Retain the existing causal `support_bounce` detector. The engine's range mechanisms are different rules; no exact support-bounce RuleSpec is implied. |
| Resistance breakout | FX order clustering motivates continuation beyond known levels; crypto support/resistance and channel rules have mixed cost and out-of-sample results. [Osler 2001](https://www.newyorkfed.org/research/staff_reports/sr125.html), [Hudson–Urquhart](https://link.springer.com/article/10.1007/s10479-019-03357-1) | Use existing `cost-breakout-v1` as the first fixed comparison reference. A scanner pivot-zone crossing does not equal its rolling-range entry predicate. |
| Breakout retest | The reviewed papers do not directly validate this project's separate-visit retest, ten-candle expiry or volume settings. | Prepare `breakout-retest-v1` versus `cost-breakout-v1` first because both fixed v4 methods already exist. This is an engineering priority, not an empirical superiority claim. |
| Trend pullback / moving-average reclaim | Moving-average rule research motivates studying trend context; it does not establish a pullback-specific or VWAP-reclaim effect. [Corbet et al.](https://doras.dcu.ie/25053/1/The_effectiveness_of_technical_trading_rules_in_cryptocurrency_markets%5B1%5D.pdf) | Fixed engine trend-pullback and VWAP-reclaim methods exist. Additional scanner recognizers and their exact source mappings need their own definitions and evaluation. |
| Compression / range breakout | Channel-breakout studies examine constrained ranges, with mixed results; they do not validate our six-bar compression and ATR thresholds. [Deprez–Frömmel, Appendix B](https://backoffice.biblio.ugent.be/download/01HY3C3S169G1N6QNYR55NZMFB/01HY60XZGZYHNQ6188MSVJT0SG) | The fixed engine compression method exists. A scanner compression recognizer remains a separate addition. |
| Failed breakout / reclaim | None of the reviewed sources directly tests the proposed project definition. | Keep as a later, explicitly defined hypothesis. Existing washout-rebound or VWAP-reclaim methods must not be relabeled as an exact failed-breakout detector. |

All pivot widths, moving-average periods, volume multiples, ATR tolerances and
expiry windows below or in the engine are frozen project definitions. These
papers supply research rationale and evaluation methods, not calibrated values
for this venue, timeframe or implementation.

## Initial recognizers and their causal meaning

Reuse the three existing `candle-patterns-v1` recognizers. Their thresholds are
project definitions, not empirically proven settings from the papers above.
Original records retain their detector identity, input cutoff and explanation.

| Recognizer | Required observed sequence | Refusal or unknown to preserve |
| --- | --- | --- |
| `support_bounce` | A confirmed support zone exists before the event. A separate later visit follows a candle entirely above the zone; the event holds its lower boundary and closes bullish above its upper boundary. | A continuous touch is not another visit. A close above support alone is insufficient. Missing volume can leave price recognition intact with volume confirmation unknown. |
| `resistance_breakout` | The preceding close was at or below known resistance; the event closes above the zone. The level must already be usable before the event. | A wick across the boundary is insufficient. Recognition does not prove order execution or a profitable continuation. |
| `breakout_retest` | An earlier breakout is followed by a full candle above the zone, then a separate later bullish return that holds the zone and closes above it. | Same-candle ordering is unknown. Failed holds and an expired retest remain failures of this definition. |

The frozen v1 parameters are two left and two closed right candles for a strict
pivot, zone half-width 0.0015 of pivot price, ten candles maximum for retest,
and volume confirmation at least 1.5 times the preceding twenty-volume median.
A pivot's historical time differs from its confirmation time. Its level first
becomes usable after the confirming candle; it cannot justify an earlier event.
One full candle range must leave a zone before a new visit is counted.

The candle-study display has explicit bounded zone/pattern retention. The
persistent scanner retains its paginated original findings separately. The daily
shortlist must not treat either a display cap or the five-card limit as authority
to discard underlying history or claim no other findings exist.

## SMA, VWAP and volume

SMA10/50/100 are means of completed native closes. Periods mean candles, not
minutes: SMA100 on 4h requires 400 hours of contiguous input, while SMA100 on 5m
requires 500 minutes. An incomplete warmup is unavailable, not a default value.

The existing chart VWAP is a trailing fifty-candle approximation:
`sum(((high + low + close) / 3) * volume) / sum(volume)`.
Keep that window and label visible. Exact traded VWAP is total traded value
divided by total traded quantity over a specified interval; it is also an
execution benchmark. A UTC-day or event-anchored VWAP would be a separately
defined calculation, not a silent relabeling of the current series.
[IBKR VWAP definition](https://www.interactivebrokers.com/campus/glossary-terms/volume-weighted-average-price-vwap/)

Relative volume compares the event's native base-asset volume with the median
of the preceding twenty same-frame positive volumes, excluding the event.
Current or baseline zero volume leaves confirmation unknown. Base quantities
are suitable for within-market ratios; they are not directly comparable across
different coins. Cross-market liquidity needs recorded quote-value measures.

Binance.US documents all five native intervals, base and quote volumes, and a
stream field identifying completed candles. Historical pages have a maximum of
1,000 candles. Documentation does not guarantee a full year for every market.
Preserve native timestamps, observed coverage and missing intervals; never
manufacture candles by carrying a previous close into missing slots.
[Official candlestick endpoint and stream documentation](https://docs.binance.us/#get-candlestick-data)

Gaps reset dependent indicator and pattern windows. Historical findings remain
readable with their original segment and source; later complete data does not
retroactively repair an earlier gap. Higher-frame context uses only the latest
higher-frame candle actually closed by the assessment cutoff. Five frames from
one price path are correlated context, not five independent confirmations.

## Daily five are research priorities

The daily policy must freeze its assessment cutoff, eligible roster, exclusions,
ranking definition, actual ranking inputs and source/progress identities. It
should return at most five distinct markets with a named reason and a path to
the saved charts and original findings. Deterministic tie-breaking is necessary
for reproducibility; it is not evidence of relative economic quality.

Distinguish detected setups from history preparation priorities. A market with
no prepared native frame can be useful next work, but must be labeled
`history pending` or its equivalent. A recognized setup requires at least one
prepared native frame; the other four frames may remain incomplete, with all
five frames' actual coverage disclosed. A history priority has no invented pattern, indicator,
probability, target return or completed-year claim. Return fewer than five when
the available evidence does not justify five admissible priorities.

For detected setups, show actual pattern state, source freshness and coverage,
volume confirmation, SMA/VWAP relationships and known opposing zones. Any
cost-room criterion needs observed spread and the applicable fee/cost contract;
absent executable inputs remain unknown. Do not turn a descriptive distance or
relative-volume score into an expected net return.

Retain all eligible findings and excluded/unknown reasons beneath the shortlist.
Group a market's overlapping events and frames rather than using correlated
copies to fill all five places. Preserve each daily assessment across restart;
new information creates a new assessment instead of rewriting the old one.
Financial execution, funding, risk limits and model/research admission retain
their existing owners and protections.

## Scanner extensions and implemented bank methods

The scanner currently recognizes support bounce, resistance breakout and
breakout retest. Trend pullback/reclaim and compression are future **scanner
recognizers**; displaying SMA or VWAP does not implement them. Separately, the
existing engine's v4 strategy bank already implements fixed `trend-pullback-v1`,
`vwap-reclaim-v1` and `compression-breakout-v1` predicates in
[`redesign_strategy.py`](../../src/trading/redesign_strategy.py). Their source
implementation is not evidence of profitability or an exact match to a scanner
finding.

A scanner compression extension could use a frozen prior range/volatility
definition and a later close beyond it. Low activity, zero volume and gaps can
mimic compression. A trend pullback/reclaim extension could use recorded average
ordering/slopes and a later closed reclaim of a named level, average or scoped
VWAP. Keep those definitions separate from existing bank predicates.

Before either addition, specify its windows, threshold, confirmation delay,
invalidation, source segment and parameter identity. Freeze those choices before
evaluation. Do not select whichever level, average, window or pattern happened
to make a consumed historical event look successful. More elaborate geometric
labels require equally reproducible definitions and their own validation.

The first proposed finding-to-research slice is narrower: prepare an immutable
issued Lab bundle, a fixed BTCUSD v4 retest-versus-breakout proposal, and the
existing deterministic current-input evaluation or an explicit retained wait.
Preparation does not submit the proposal to the inbox, dispatch a model, reserve
slots or fund accounts. Its source mapping and required separate executable
inputs are specified in
[`PATTERN_RESEARCH_COMPARISON.md`](PATTERN_RESEARCH_COMPARISON.md). It does not
complete autonomous strategy development, a prospective trial or an economic
learning cycle.

## Verification and economic evidence

Recognition tests must prove prefix invariance: appending or altering future
candles cannot change an already emitted indicator or pattern. Cover strict
pivot ties, confirmation timing, forming candles, duplicates, gaps, zero volume,
baseline exclusion, separate visits, failed holds, retest expiry and native
frame alignment. These establish software causality, not market profitability.

Economic evaluation needs time-ordered development and later untouched periods,
actual venue/cash-only constraints, fees, spread, slippage, unfilled orders and
ambiguous intrabar execution handled conservatively. Report net expectancy,
uncertainty, sample size, turnover, drawdown and matched baseline outcomes.
Repeated touches, overlapping holdings and simultaneous frames are dependent
observations; raw event count is not independent sample size.

Retain every tested rule, parameter set, market and timeframe. Selecting only
the winner understates the search. Sullivan, Timmermann and White's Reality
Check examines performance over the full rule universe while adjusting for
data snooping. A later prospective evaluation must likewise account for all
attempted choices rather than attaching an unadjusted significance claim to
the best-looking shortlist.
[LSE primary paper](https://www.fmg.ac.uk/publications/discussion-papers/data-snooping-technical-trading-rule-performance-and-bootstrap)

Source fixtures, compiled UI behavior, actual retained native data, prospective
pattern outcomes and after-cost financial evidence are separate proof stages.
Daily automation makes evidence collection repeatable; it cannot itself
establish a trading edge, qualification or permission to change a strategy.
