# 0001 — Start with a local public snapshot monitor

Date: 2026-09-27. Scope: initial CP0/CP1 work, before any financial state.

The first usable workflow is observe → inspect → pause → restart → reopen → export
and replay. The four watchlist entries are research comparisons, not selected live
markets. This avoids inventing fills, profitability, account eligibility, or funding.

Use the foundation's Python/FastAPI and TypeScript/React direction. Combine collector
and API in one local process for this checkpoint. Use SQLite for bounded public
observations and the operator pause flag. This deliberately narrows the proposed
PostgreSQL/Parquet storage plan: there is no ledger or financial data in SQLite.
Introduce PostgreSQL, migrations, and financial concurrency tests when CP2 actually
needs them. Long-term research datasets can then use partitioned files/Parquet.

Use complete REST snapshots, not an incomplete diff-stream implementation. The
initial monitor explicitly cannot establish tick-level continuity or support an
economic fill model. Book identifiers may jump between polls; regression and changed
duplicate identifiers are rejected. Missing intervals stay missing. If a genuine
venue sequence reset occurs, investigate and establish a separately recorded new
observation dataset; do not silently rewrite earlier evidence.

Observed public metadata and depth calls succeeded on 2026-09-27. The first metadata
request failed because the `symbols` parameter included spaces; compact JSON succeeded.
Preserve that failing receipt and test compact encoding. See `../evidence/public-probe.json`.
The adapter uses the official [Binance.US public API contract](https://docs.binance.us/#get-order-book-depth)
and observes rate-limit delays. No account terms or permissions were verified.

Consequences: low local setup cost; one inspectable runnable application; no external
database service yet. This is not a shortcut for financial durability, a deployment
architecture, a broker selection, or full CP0 economic feasibility proof.
