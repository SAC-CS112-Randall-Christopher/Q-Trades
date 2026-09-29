# Next: CP2 economics; CP1 implementation audit and CP0 installation remain distinct

CP1's risk fixes, account-scoped policy adoption, recovery API and normal UI are
implemented in the CP1 branch. See [the behavior and boundaries](CP1_PAPER_RISK.md)
and the CP1 review evidence. Preserve earlier policies and all account history.

Next product work is CP2's whole-account return comparisons, open positions,
consistent cost profiles and benchmarks. Do not claim those evaluation defects
were corrected by CP1. No new model dependency belongs in the trading loop.

CP0 still requires approved merges and the actual first workstation update. Its
simple batch script and C:\Projects\Q-Trades\logs location are unchanged by CP1.
No merge, native update, account policy change or live trading was performed here.

---

## Historical pre-CP1 work order

# Next: finish the simple CP0 update, then CP1

The source import is draft PR #2. PR #3 has been simplified at Chris's request:
**Update Q-Trades.cmd** is the only normal update entry point. The script uses
standard Git, npm, pip, robocopy and the existing Windows task. No release manager,
new runtime folder, task repointing or separate activation workflow.

Verify the small updater in isolated Windows fixtures, merge after approval, then
perform the first authorized real update and confirm the running commit and health.
No new batch of tests in another Windows verification folder is the normal workflow.
Keep CP1's existing branch/fixtures; its risk fixes are not included in CP0.

---

# Current checkpoint

The September 28 review prioritizes **reliable paper valuation and risk boundaries**. Follow checkpoint A in [the analysis](reviews/2026-09-28-analysis.md) and [the implementation directive](PRODUCT_DIRECTION_2026-09-28.md).

The older observation checklist follows for historical context. Its options expansion and replenishment assumptions are not current default permissions. Do not restart, stop or alter a running experiment until its current state and original policy have been inspected.

---

# Next evidence checkpoint

The $100 Tier 3 paper loop is running under [this contract](LEARNING_EXPERIMENT.md).
Do not reset the account or invent trades to demonstrate activity.

1. Observe naturally triggered forward paper fills and verify their source books,
   fees, stops, exits, and entry rejections.
2. Verify the first naturally scheduled four-hour review and any eventual promotion.
   Synthetic clock tests prove mechanics, not a completed reporting period.
3. Accumulate outcomes: after-funding net P&L, drawdown, wins/failures/open attempts,
   elapsed time, costs, and exposure by version. Trade win rate is not the $1,000 goal.
4. Audit simulation realism: latency, dynamic filters, costs, stream gaps, and passive
   benchmarks. REST snapshots do not establish live stop execution or account fees.
5. Investigate failures with isolated fixtures and preserve the actual running journal.

6. Verify genuine push connectivity and event latency; current public REST fallback
   must never be reported as a connected 100 ms stream. Inspect candidate demotion,
   held-position priority, capture pruning and sustained CPU/disk growth.
7. Compare paired universe accounts after costs without pooling balances or treating
   correlated shadows as independent successes. Keep discovery policy versions.
8. Verify futures snapshots appear in a naturally completed four-hour review and
   in naturally triggered trade receipts. Inspect gaps, units and one-venue coverage.
   Do not treat rising open interest or positive funding as a proven trade signal.

9. Inspect the separate options historical replay: source dates, skipped contracts,
   cash reservations, next-session fills, unsettled proceeds and four-hour reviews.
   Do not conflate its historical sessions with live spot results. Do not force trades
   when full premium plus fees exceeds the $2.50 initial risk budget.
10. Validate an eventual naturally qualified historical option trade and its later exit,
    plus ongoing end-of-day coverage after the initial 90-session catch-up. Missing
    exercise/expiry disposition must remain blocked, never a guessed cash payout.
11. Follow the [free live-data investigation](research/2026-09-27-live-options-data.md).
    Chris accepts opening a free account; Public is the preferred candidate to verify.
    Confirm zero-cost live entitlement, funding conditions and minimum credential
    scope before integration. Preserve the historical account when adding a separately
    versioned forward experiment. No subscription, deposit or broker orders authorized.

Tier 1 equities, Tier 2 research, live options data/execution, broker eligibility,
backup/restore drills and optional AI remain distinct further work. Public hosting is
outside the user's local-only direction. For brokers, resolve IBKR's T+0 documentation
against actual cash-account reuse/credit terms before implementing that assumption.
