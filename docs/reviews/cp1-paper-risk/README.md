# CP1 implementation audit — September 29, 2026

## Outcome and scope

Implementation commit: `0ac3105956808178c0a66ea77ade9e023bea4c1d`.
Exact CP0 base: `d20dced2834d237b9421d6b3c3b26b08bb90256a`.
Draft PR: #4, stacked on draft CP0 PR #3. This is an implementation audit, not an
operating Windows deployment, an independent external review, or a trading-return
claim. CP0's actual workstation update is still outstanding.

The operator can see why each paper account is blocked, adopt the hard-stop policy
explicitly for an older account, and resume an eligible stop without adding capital
or lowering its loss reference. Missing held-asset valuation cannot permit a
reserved buy. Executable exits and healthy sibling accounts remain independent.

## Acceptance reviewed

| Requirement | Evidence |
| --- | --- |
| Missing BTC after ETH reservation prevents new ETH exposure | Both original regressions failed on the exact base. Engine tests now pass, including a direct fill call with a previously true freshness flag. |
| Recovery cannot duplicate a fill or release reservations twice | Repeated outage/recovery observations, transaction rollback and database close/reopen tests preserve cash, positions and a single cancellation journal event. |
| Exits remain possible and siblings remain usable | Missing other-held-symbol and insufficient-depth cases retain partial/complete exits and a healthy sibling buy. |
| Hard loss stop survives review and restart | New-policy review/reopen and below-$5 failed-attempt tests retain the stop/reference, losses and funding. |
| Deliberate, idempotent recovery | Current complete valuation above the unchanged limit, exact stop number, retry/restart, stale earlier request, daily/global/failure/cooldown refusal, and recovery transaction rollback. |
| Existing policies/history are protected | Unversioned history remains labeled legacy; confirmed account-scoped opt-in is one-way and journaled. Historical replenishment test fixtures explicitly identify their old policy. |
| Normal UI makes cause and next action visible | Compiled browser/API acceptance: policy confirmation, hard-stop refusal, global-pause distinction, successful recovery/reload, failed-response retry, exact BTC blockage and comparison accounts at 1440px/360px. |
| No default derivatives-account expansion | Fresh hard-stop spot startup does not create an options account. Existing options history is retained. |

## Finding discovered during implementation audit and corrected

**Aging-quote recovery (corrected before the implementation commit).** The initial
change set timestamped every successful valuation with the current tick. A held
quote aged 4.9 seconds could therefore appear recoverable 0.2 seconds later even
though the underlying quote was older than the existing five-second limit.
`test_recovery_cannot_extend_the_age_of_the_underlying_held_quote` failed on that
implementation. Valuation/recovery freshness now retains the oldest required held
quote time. The new test passes, and the API's account freshness agrees with it.
The failing receipt is `audit-stale-quote-before.txt`; it is retained, not regraded.

The audit also checked that the global resume operation cannot clear a hard stop,
that an old recovery request cannot clear a later stop, that denied control writes
roll back, that unknown explicit policies do not inherit legacy permissions, and
that pending-buy cancellation retains the original balanced reservation journal.
There is no new funding endpoint, model authority or second financial ledger.

## Executed verification

- **Full Linux suite: 250 passed, 19 skipped**, one preexisting Starlette TestClient
  warning, 3.77 seconds. The 19 skips are 14 Windows updater cases and five Windows
  supervision cases. PostgreSQL tests ran on the dedicated disposable UTF-8
  PostgreSQL 17.11 cluster, not the operating Windows/PostgreSQL 18 accounts.
- **Windows PowerShell 5.1 CI: 65 passed, 12 skipped**, one preexisting warning,
  39.71 seconds, exact implementation commit above. Run 36589087996:
  https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/36589087996
  The 12 skips are the unconfigured PostgreSQL cases in this Windows CI selection;
  their corresponding cases ran separately in the Linux disposable database.
  Git/robocopy are exercised on disposable paths; Windows service actions are mocked.
- Ruff, strict mypy (35 modules), compileall, TypeScript and Vite production build
  passed. These are scoped code checks, not proof of profitability or deployment.
- Retained public depth/sequence/filter data from `first-market-capture.json` also
  exercises the buy-blocking boundary. The outage uses explicit synthetic receipt
  times and account conditions; it is not a historical strategy backtest.
- Final browser run used the actual compiled dashboard, API and TieredPaperRuntime
  with an in-memory synthetic account store and no live market collector. It passed
  the seven checks in `browser-results.json`, with zero page errors, unexpected HTTP
  error responses or blocked non-loopback browser requests. No horizontal document
  overflow at 1440px/360px. Real PostgreSQL persistence/rollback/restart is proven by
  separate tests, not claimed for this browser fixture.

The first risk-focused browser harness substituted the base PaperRuntime and its
unrelated station endpoints raised missing-method errors, despite the risk controls
passing. That harness was corrected to use the actual TieredPaperRuntime, and HTTP
failure assertions were added before the final clean rerun. Product code did not
change to accommodate the harness. This failed harness coverage is not evidence of
an operating station defect. Only the final rerun is used for integrated UI evidence.

Counts across runs overlap and are not additive. `provenance.json` records code and
retained-data hashes. The originally preserved two-test fixture remains unchanged
in the private validation directory; its expanded successor is committed in tests.

## Remaining boundaries / handoff

No operating account was converted, reset, funded or restarted. No merge, native
installation, new provider/model call, fee recalibration or live trading occurred.
The simple CP0 batch updater and its requested log path are byte-unchanged by CP1.
The preexisting historical options/refill directions are not new default grants;
legacy behavior remains visible until the relevant account is explicitly opted in.

A stopped cash-only account below its original loss boundary cannot recover by
pressing resume; it remains a retained failed/stopped experiment. Later campaign
setup belongs to CP3, not a concealed top-up here. CP2's whole-account economics,
fee profiles and benchmarks remain next. Do not close the parent roadmap or claim
CP0/CP2–CP9 completed from this implementation audit. Final workstation use still
requires approved merges and the normal manual updater.
