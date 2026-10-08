# Candle and volume workspace

This source lane implements Chris's requested 5m, 15m, 30m, 1h and 4h candles,
moving averages, VWAP, support/resistance and volume inspection. It starts at
`fdb5f1490cb9d0b433d96da846827150a75f159e` in
`codex/candle-volume-patterns-66`, independent of the other open research and
desktop PRs. Source and disposable QA acceptance do not update the installed
application or authorize a trading strategy, research-role change or model call.

## Normal workflow

In Markets, select a market and use **Candle & volume workspace**. Select an actual
native interval and history window, then load a study. The chart shows closed
OHLCV candles, volume, SMA 10/50/100 and approximate VWAP. Toggle each overlay,
inspect a candle, or select a recorded bounce, breakout or retest to inspect its
price level, time, volume baseline and recorded reason. Saved studies reopen the
original observations; a reload never silently substitutes today's candles.

The workspace requires the existing paper/runtime instrument identities and
configured research-storage owner, but a historical read does not require the
paper service to be trading. It uses the existing public venue request budget,
optional-tool concurrency/free-disk checks, ToolJournal and ResearchStorage.
No chart observations are inserted into the financial database or engine's
rolling inputs. The account strategies, decisions, orders, fills, funding,
history, twenty-slot capacity and storage policy remain owned by their existing
components.

## Explicit analysis settings

| Setting | Version 1 behavior |
| --- | --- |
| Candles | Binance.US native closed UTC intervals; forming candles excluded |
| SMA | 10, 50 and 100 candle periods in the selected interval |
| VWAP | Trailing 50 candles; HLC3 typical price weighted by base volume |
| Volume baseline | Median of the preceding 20 consecutive candles; excludes current candle |
| Volume confirmation | Current volume at least 1.5 times that baseline; descriptive setting |
| Missing/zero volume | Zero or incomplete baseline gives unknown confirmation; malformed values refuse the study |
| Pivots | Two candles to the left and right; level usable only on the next candle after confirmation |
| Price zone | Fixed plus/minus 0.15% around the confirmed pivot |
| Visits | Separate touches require leaving a zone; continuous residence is one visit |
| Retest | A prior close above resistance, departure, then a qualifying retest within ten candles |
| Pattern display | Latest 60 records and 12 active zones; omitted pattern count disclosed |

SMA periods are **not literal daily averages**. The trailing VWAP is an OHLCV
approximation, not exact trade-level or session VWAP. Gaps reset indicators and
active levels; no missing candles, volumes or touches are invented. Zone touch
totals summarize later history too and are labeled as such. The event itself
uses only information available at that closed candle.

These labels organize observations into testable hypotheses. They do not
establish win-rate improvement, profitability, probabilities or after-cost edge.
No automatic execution or researcher activation is part of this lane.

## Coverage, resource bounds and recovery

The default is 240 candles. Windows include one week, one month, six months and
one year, with at most 5,000 returned candles, six pages of at most 1,000 rows,
and a 25-second source-read deadline. A request exceeding the candle budget
starts at the most recent 5,000 possible intervals and explicitly reports
truncation. For example, a complete 4h year has 2,190 candles; a 5m year cannot
fit and its study covers roughly the latest 17 days. Requested and returned
bounds, missing count, warmup and omissions remain visible.

An incomplete, unordered, duplicated, malformed or wrong-duration source candle
refuses the study and retains the failed receipt. It is not resampled, silently
discarded or replaced by a synthetic observation. Historical candles retrieved
now are not inputs that the paper engine observed when it made earlier decisions.

Full inputs and chart points are retained in fixed 500-candle chunks under the
existing 2 MiB packet cap. A manifest and every chunk are verified and protected
for the configured existing temporary-retention interval. The hot receipt stays
within its existing size policy. No quota, database or storage reserve is raised.
After existing retention expires, exact history can become unavailable; reopening
reports that condition without a current-data substitute.

The original receipt body stays bound to `result_sha256`. The separately expanded
`candle_analysis` stays bound to the manifest reference and
`envelope.candle_analysis_sha256`; its exact raw source is checked too. Namespace,
run, account and timeframe/window identities are verified before hydration.

A saved request UUID identifies one original request. Repeating it returns the
original completed, failed, interrupted or running receipt without refetching.
The browser retains unresolved request identity before dispatch, coordinates
that record across windows, and uses an exact GET to reconcile a lost reply.
A missing GET result remains unknown; it never authorizes an automatic POST retry.
Changing view or selection cannot publish an earlier response into a new scope.

## Source references

The native interval and paging contract follows the public
[Binance.US API documentation](https://docs.binance.us/). Chart rendering uses
the installed Lightweight Charts 5.2.1 API and its
[version 5 documentation](https://tradingview.github.io/lightweight-charts/docs/5.0).
The fixed pattern/volume settings are explicit product hypotheses, not calibrated
claims from these technical references.

## Acceptance ledger

The accepted installed rollout is reused; no operating update, collector rebuild
or service restart is performed.

| Check | Executed result |
| --- | --- |
| Pure analytics author suite | 45 passed, no skips; included in the affected selection below |
| Affected backend selection | 126 passed, 10 skipped; nine absent disposable-PostgreSQL prerequisites and one Windows developer-mode symlink prerequisite |
| Final heavy-gap correction | One passed: 2,500 returned bars in 5,000 interval slots, all 2,499 gaps reopened exactly |
| Maximum study | Actual API save/reopen of 5,000 normal native fixture candles; separate 5,000 legal long-decimal retention/reopen larger than 2 MiB before chunking |
| Recovery | Retained running request from another journal owner causes zero repeat venue calls; receipt body hash and exact expanded analysis remain valid |
| Static source | Ruff source/tests and strict Windows-platform mypy over 114 source files passed |
| Dashboard | TypeScript and Vite production build passed; existing main-bundle size warning retained |
| Independent backend review | Four material findings repaired and current source hashes rechecked clear; reviewer read retained author evidence and did not claim to execute tests |

All local evidence is retained under the task's output directory, including
JUnit results, hash-bound independent reviews, exact synthetic studies, build
logs, browser receipts and screenshots. Private financial rows and operating
identities are not uploaded. Earlier failures remain failures: restricted-token
pytest temporary-folder permissions; an incorrect scratch journal pathname
(16 passed/one failed before correction); sandbox Vite spawn refusal; initial
formatting errors; a browser harness locator failure and a subsequently discovered
same-ID navigation recovery defect. Corrections are recorded separately.

Two bounded actual BTCUSD public reads gave distinct results. Recent 5m returned
240 valid contiguous candles. Recent 4h returned 238 rows and was refused because
one August 31 candle ended at 03:56 UTC rather than its 04:00 boundary; two later
4h intervals were also missing. The original aggregate source-smoke receipt stays
false. No source validation was relaxed, and those gaps are not profitable-pattern
or uninterrupted-market evidence.

One additional, different 4h **week** window passed: 42 of 42 actual native closed
candles, no gaps or truncation. SMA 10 and the prior-volume comparison warmed up;
SMA 50/100 and the 50-candle VWAP remained unavailable because 42 candles are
insufficient. This one public read does not rewrite the refused recent window.

Compiled dashboard acceptance exercised **17 distinct groups** against the actual
disposable API, native synthetic transport, registry, journal and research store:
all five intervals; pattern/candle/volume inspection; full 5,000-candle archive and
reload; missing bars/warmup; failed source; definitive refusal; lost replies and
exact GET recovery without a repeat POST; late-response scope changes; unavailable
saved results; delayed-lock scope changes; same-ID/cross-market/account recovery;
mobile geometry; and continuous versus warmed-gap plots and viewport positioning.

The local execution is deliberately split: browser run 1 passed eleven groups then
failed a test locator; run 2 passed two remaining groups then exposed the same-ID
navigation defect; run 3 passed its two repaired navigation/mobile groups; run 4
passed two focused chart-gap/viewport groups after visual repair. The first two
aggregate receipts remain false. Earlier successful groups were reused; this is
not a claim that one final full local harness invocation passed. A final caption
clarifies UTC chart axes versus Mountain-time inspection/crosshair and only requires
a build. Screenshots explicitly label their synthetic source. Financial state in
the fixture stayed exact; no external browser requests, page errors or model calls
were observed in the retained successful scopes. Every owned QA server/browser was
stopped; no operating task was restarted.

Independent frontend review repaired stale recovery callbacks, an unsent pending
request, missing-candle substitution, same-ID restore state, cross-market fallback,
indicator lines bridging missing observations, and whitespace-insensitive viewport
indices. Backend and frontend reviews bind their respective source bytes and proof
limits. CI runs the new native cases in the existing persistent-research job and
the 17-group browser harness in the existing browser job, preserving the native
suite's already-tight eight-minute budget and every existing test selector.

Hosted exact-head results are tracked on the owning draft PR. An installed rollout
remains separate. No win-rate improvement, financial integration rerun, complete market
history, automatic strategy selection or native Windows package acceptance follows
from these source/disposable checks.

The pre-existing broad research Goal remains incomplete. The Goal harness rejected
creation of a second objective while that Goal exists; it was not falsely completed
to bypass the constraint. This bounded source lane has its own branch, worktree,
tests, review and PR evidence.
