# CP2 implementation audit — September 29, 2026

## Outcome and scope

Draft PR #5, stacked on CP1 PR #4. Base:
`ca92d5bfa3659d8284d7ff22db07c1dd65a428a2`.
Financial implementation: `90db4f774e367a2d45042bd4524866bcded0a037`.
Final UI code: `63fa3e26c21172b63643e5eb1d7b01f80f628993` (collapses repeated ranking
explanations into accessible details; no financial logic change).

The normal Paper screen now explains whole-account results, cash/reservations,
open P&L, execution costs, estimated operating allocation, and matched comparisons.
It permits prospective fee/operating assumptions without repricing historical fees
or changing account funding. The implementation was source/behavior reviewed after
construction. This is not an independent external audit, a native deployment, or
proof of a successful trading strategy. CP2 remains draft while acceptance is pending.

## Acceptance reviewed

| Requirement | Evidence |
| --- | --- |
| Whole-account rather than winning-trade averages | The exact CP1 counterexample promoted a candidate with $90 equity from attractive closed trades. CP2 refuses that unsupported promotion. Separate unequal-position-size and open-loss/cross-window cases pass. |
| $50/$100 reconciliation | Both starting balances and both execution scenarios exercise reservations, acquisition, disposal, costs, realized/open P&L and per-asset reconciliation. Reinitialization cannot replace existing history. |
| Funding is not profit | Funding-adjusted returns and dollar P&L exclude external flows; flow windows are not ranked. Zero-NAV legacy replenishment retains losses without claiming a return recovery. |
| Comparable costs and controls | Capital/funding/profile/risk/operating cohorts, unknown costs, intermediate missing marks, gaps, changed settings and partial/dust control marks are tested. |
| Reporting does not double charge costs | Gross reference minus execution attribution equals net trading; operating allocation subtracts once in reporting and never debits paper cash. |
| Settings persist through normal workflow | API authorization, version conflicts, flat-only fee changes, duplicate submission, storage errors/rollback and reopen tests pass. Browser tests exercise actual UI/API save, reload and lost-acknowledgment retry. |
| Execution is conservative and evidence-linked | Shared later-book/IOC/partial/filter/fee arithmetic; duplicate cancellation and repeat-book no-double-fill controls; unsupported non-USD fee assets rejected. Retained public depth/filters are tested with disclosed synthetic timestamps. |
| UI consistency and uncertainty | Paper screen and Strategy Lab use current account profiles and account-window selection language. Missing marks and disconnected values are not current profit; historical results retain their original scoring label. |

## Findings discovered and corrected during this audit

1. **Small-account inheritance:** newly created universe comparison accounts still
   used the old hardcoded $100/legacy defaults. They now inherit the declared
   original capital and execution profile; previously created accounts are unchanged.
2. **Unknown primary execution profile:** review could raise while checking the
   primary profile and interrupt healthy sibling comparisons. Unknown primary
   assumptions now prevent promotion without granting substitute fee permissions.
3. **Operating-cost ranking:** rankings initially used net trading return before
   the declared operating allocation. The differing-window-capital counterexample
   demonstrated an incorrect ordering. Rankings now use after-operating returns;
   unspecified operating costs remain unknown and unranked.
4. **Compounding:** summing two window returns could select the wrong challenger.
   The retained 50%/1% versus 25%/25% arithmetic fixture fails before correction and
   passes with multiplicative compounding. These are synthetic test returns, not
   observations or targets to raise risk limits.

The original failing runs remain in audit-before.txt and audit-ranking-before.txt.
The closed-trade baseline/corrected outputs are retained separately. Repository
text copies trim terminal trailing spaces only; raw runs remain in private validation.

## Executed verification

- **287 passed, 19 Windows-only skips**, one existing Starlette TestClient warning,
  4.63 seconds on the final financial code. The 19 skips comprise 14 Windows updater
  cases and five native supervision cases. Database cases used the existing dedicated
  disposable UTF-8 PostgreSQL 17.11 cluster, not operating Windows accounts.
- **37 focused economics/store cases passed**, including both original-capital and
  execution-profile combinations. Counts overlap with the full suite; do not add them.
- Ruff, strict mypy (37 source modules), Python compilation, TypeScript and Vite
  production build passed. Final row-layout polishing passed the build/type checks
  again; it did not change financial code.
- Final browser/API run at the final UI code passed **eight checks**: displayed
  after-operating return equals the actual API; profile changes preserve cash;
  reload and lost-success-response retry; held-position profile refusal; unavailable
  holding marks with accessible rank explanations; desktop/360px layouts; automatic
  recovery when prices return. Zero page errors, unexpected HTTP errors or blocked
  non-loopback requests; no horizontal document overflow.
- Browser accounts, quote transitions and accelerated historical timestamps are
  explicitly synthetic in-memory fixtures. The API, compiled UI and TieredPaperRuntime
  are real. PostgreSQL persistence/rollback/reopen are verified by separate tests,
  not asserted from a browser reload. Screenshots are visibly labeled QA fixtures.

## Windows CI is blocked, not passed

Run 36615568896 at the exact financial implementation commit did not start a runner.
Its job has zero executed steps. GitHub's annotation is:

> The job was not started because an Actions budget is preventing further use.

Run: https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/36615568896

This is a budget/infrastructure blocker, not a CP2 assertion failure. No CP2 Windows
pass is claimed, and earlier CP0/CP1 Windows results do not replace this verification.
No billing/budget setting was changed and no retry loop was started. The configured
Windows test selection remains available when capacity is authorized. See
windows-ci-blocked.json for exact run, commit, steps and annotation provenance.

## Limitations and handoff

The 50/50 BTC/ETH control starts a fresh hypothetical allocation each window using
that account's window-opening equity. It is not a continuously held buy-and-hold
portfolio. Fees, observed filters and later-book fills use the shared execution
routine; resting maker fills, hidden liquidity and live broker status are not modeled.
Benchmark state is analytical and cannot authorize spending or fund an account.

USD-quote fee charging is an explicit paper assumption, not verification of the
operator's venue account, commissions or settlement eligibility. The original fee
scenario remains the default/stress profile. The optional public schedule is dated
and never overwrites historical fills. Source details: ../../CP2_ACCOUNT_ECONOMICS.md.
The frozen numerical preflight retains its old assumptions rather than being repriced.

Two four-hour windows and the disclosed thresholds govern bounded paper selection;
they are not dependence-aware statistical qualification or profitability evidence.
Campaign creation and ten concurrent accounts belong to CP3; no account-creation
UI or new capital/funding endpoint was added here. No model is on the execution path.

CP0's updater and its log-path files are byte-unchanged. Existing native account
history, worker, source, risk policy, model runtime and database were not modified.
No merge, deployment, native restart, paid inference or live trading occurred.
Main still contained only the original README at the latest source check.

Remaining acceptance: Windows tests when CI budget permits, approved merge and
normal native installation, and real operator workflow verification. Do not mark
CP0/CP2 or the parent roadmap fully deployed from the Linux/browser evidence.
Do not roll back pre-CP2 code over new-profile history; old source does not understand
these profile fields. Continue with the existing forward-update workflow.

The committed images are actual viewport captures after quote recovery. Tall-element
captures can include off-viewport fixed elements; the viewport probe confirmed the
unfocused skip link was above the viewport (top -60px, bottom -16px). No product
CSS was changed to hide an accessibility control for these screenshots.
