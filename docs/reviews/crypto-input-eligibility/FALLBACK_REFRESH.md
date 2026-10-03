# Refresh expiring books within the existing budgets

This source candidate follows the merged and installed PR44 diagnostics at
`4c5cb452`. It is not installed. A new merge/install needs the existing explicit
operator approval; the prior PR44 authorization has been fulfilled.

## Original timing evidence

The later retained sample contains five BTCUSD exclusions in 24 inspected
decisions. This is that sampled set, not a measured overall outage rate or a
continuous execution window. In those five decisions, the WebSocket book was
present but its existing freshness score was approximately 1,067-1,254 ms, above
the unchanged 1,000 ms limit. Its event age at receipt was about 263 ms and clock
uncertainty about 289 ms, leaving about 448 ms of usable elapsed receipt age.
The cached REST fallback was about 1.031-1.515 seconds old, also ineligible.
Four replacement requests were in flight. The remaining decision had no request
in flight and its next permitted request time had already passed.

The original loop starts a replacement request only after the stream has lost
eligibility. An in-flight request supplies no book until its actual response
arrives. That reactive timing is a plausible contributor to the recorded gaps.
The observations do not isolate the cause of transport, rate-pacing, clock or
local receipt-processing delay. Recorded request-to-receipt elapsed time includes
provider pacing and processing; it is not pure network latency. There is no
evidence here that another pair's request blocked the observed BTCUSD decision.

The original private receipts and hashes are retained outside Git. No new venue
request or operating database query was needed for this analysis. Complete candle
history cannot replace the excluded executable book.

## Small scheduling change

The fallback loop now considers refreshing when an eligible stream book has at
most 500 ms of validity remaining under its original freshness calculation. A
healthy stream with more remaining time still needs no replacement request.
Absent or stale streams retain the existing fallback behavior.

This is a scheduling lead, not an additional freshness allowance. Stream
eligibility, REST's one-second receipt-age and round-trip limits, actual receipt
timestamps, sequence checks, financial accounting and the whole-work resource
guard remain unchanged. A pending request never becomes an input, and a later
response cannot be inserted into an earlier decision.

The existing public venue, depth endpoint and weight limiter remain authoritative.
Per-symbol spacing is still at least 0.5 seconds after a fast-tier response and
five seconds for the slower tier; in-flight requests cannot be duplicated. Global
retry and provider cooldown rules still apply. Requests can begin earlier and
may occur more often during weak streams; their actual rate, pacing and effect
need installed measurement. The loop still awaits its existing bounded request
group, so head-of-line behavior is not repaired or claimed here.

## Verification and limits

Native Windows / Python 3.12 / the verified owned QA PostgreSQL cluster:
750 passed, zero skips, 292.75 seconds. Ruff and strict Windows-targeted mypy pass
across 87 source files. There is one existing Starlette deprecation warning.
The QA schemas are disposable and separate from the operating paper database.

Three new synthetic timing checks exercise pre-expiry request dispatch and an
actual later receipt, spacing/retry/in-flight boundaries, and rejection of a
response exceeding the original round-trip limit. Both sources still become
ineligible after their original age limits. These fixtures prove software timing
behavior, not installed delivery improvement or market value.

Three additional native orchestration cases deliberately supply schema-valid
unsafe model prose about a stop override, waived fees and later-book substitution.
The compiled proposal retains the server-issued method and original evidence
bundle, and accounts remain unchanged and balanced. Unsafe prose is archived for
semantic review; these stub cases do not qualify a model or prove that all
possible unsafe recommendations will be detected.

After a separately approved installation, first measure original selection
diagnostics and actual request timing/rate under the unchanged admission rules.
Do not immediately arm another blind long capture. Required operational evidence
remains a continuous supported 2,700-second horizon with causal warmup and original
accounting, representative actual fills for fill-accounting verification, and
separately admitted model inference with continued paper health. Retain gaps and
no-trade outcomes. No rule changes, model promotion or research activation follow
from this source candidate.
