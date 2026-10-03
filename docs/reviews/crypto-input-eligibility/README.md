# Original crypto input eligibility at the finite-window boundary

This continues the capture/replay work at merged `c1cba9a`. It is source-only
diagnostic work. A new merge/install requires operator approval through the
existing updater; the prior PR #42/#43 approval is fulfilled.

## Observed boundary and remaining evidence

The original failed window retained two consecutive supported ticks, spanning
0.184870 seconds, with zero fills. The next actual financial tick had ETHUSD but
no BTCUSD frame. Runtime sends the same frame set to capture preparation and
the financial engine, so the absent frame is not evidence that capture discarded
an eligible book received by the engine.

Read-only replay of that original missing-input tick, from its own original
recorded state, matches final state, ordered events and balanced accounting using
ETHUSD alone. No BTC book was inserted. This is an isolated absence diagnostic;
it does not bridge state across the incomplete window or establish its full
2,700-second horizon. Representative fill accounting remains unproven.

The original stream snapshot explicitly marks BTCUSD fresh=false. Its recorded
event age plus clock uncertainty at the later packet cutoff is about 1,062 ms
against the existing 1,000 ms subscription guard. Genuine REST frames appear
immediately before and after the absence. This is consistent with freshness
expiry, but the original record lacks the earlier selection cutoff, exact
fallback-cache age, sequence comparison and excluded metadata/rule checks. Those
unrecorded facts cannot be reconstructed by substituting the next book.

## Bounded change

`StreamFeed.fresh_books` can populate a caller-owned diagnostic sink at its
original clock and freshness check. Runtime retains that sink alongside the
actual REST fallback age/eligibility, subscription, sequence comparison,
in-flight request and existing retry schedule, instrument presence, rule validity
and final frame decision. No extra venue call
is made. The same selected frames still go to engine and recorder.

Capture includes that original selection record and compact candle context for
all retained markets, including an excluded BTCUSD. It does not export a missing
book or backdate bars. Finite-window status identifies the first failed original
input condition and preserves these diagnostics. The admission predicate,
financial freshness limits, source timing, finite budgets, cash-only rules,
twenty-slot capacity and full-horizon verifier remain unchanged.

Native synthetic regression checks distinguish stale stream plus expired REST
fallback, a genuine later REST receipt, sequence regression, missing instrument
and invalid rules. A failed window keeps the excluded market's actual candle
context while refusing to admit its absent frame. Existing continuous-window,
accounting, chronology, rollback and replay checks remain required. Synthetic
checks establish software behavior, not market improvement or actual fills.

After an approved installation, first inspect original selection diagnostics on
the unchanged native guard. Request a new bounded window only when the actual
input behavior supports it. Required evidence remains causal warmup, continuous
eligible BTCUSD inputs and original accounting through the genuinely elapsed
2,700-second horizon; retain zero-trade results and require representative fills
for separate fill-accounting verification.

## Source verification

Final native Windows / Python 3.12.10 / owned QA PostgreSQL 17.2: 744 passed,
zero skips, 309.08 seconds. Ruff and strict Windows-targeted mypy pass across
87 source files. The earlier 743-case run is retained separately before the
in-flight-request regression. Hosted Windows checks include the stream tests;
their exact-head result is recorded in the draft PR. Installed acceptance,
continuous 2,700-second evidence and representative fills remain outstanding.
