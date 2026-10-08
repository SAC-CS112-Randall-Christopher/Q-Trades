# Continue discovery after preserving a fixed v4 comparison

The generic proposer tries to create a child of every preserved, unbranched
trial by changing its lookback. A reviewed v4 bank mechanism has fixed medium
horizon controls and a fixed lookback. Its strict validator correctly refuses
that unsupported child. The resulting exception stops the proposer before its
existing independent discovery paths run.

Skip fixed v4 parents only in that generic lookback-child loop. Keep the saved
parent intact and unbranched. The existing independent paths can then propose a
valid unused rule if the existing capacity, family, duplicate, input and
Stop/Pause conditions allow it. This does not guarantee that a proposal exists
or authorize a new financial effect. V2/v3 parents retain supported lookback
variation; v4 validation stays strict.

The reproduced before-case is retained under
`continuation-20261008-12/audit/preserved-v4-parent-reproduction-01`.
Its actual proposer raised the fixed-v4 validation error; its final evidence
writer also failed while serializing a RuleSpec in validation details. Preserve
that partial output and exit status rather than describing it as a passing run.

Verification must cover the actual proposer, strict v4 refusal, supported legacy
variation, capacity/Stop/Pause/duplicate behavior, and a genuinely preserved v4
trial through the existing disposable financial owner. Retain the original
parent, account, funding, rule and financial history; reopen the result cold.
Synthetic qualifying trades and accelerated review time are software evidence,
not a prospective experiment or an improved trading result.

The first actual disposable run (`continuation-20261008-14/root/preserved-v4-pg-01`)
failed. Its synthetic eligible observation reused a five-minute bar already
decided by the engine. The engine correctly made no new entry, and the unchanged
scorer recorded `low_information` and retired the pair. The test then failed its
active-parent lookup. Its full financial export and score remain retained; the
original journal prefix and reconciliation passed, and the exact QA owner was
stopped. A later positive control must use a new native bar and retain the actual
score before asserting preservation; this failure is not a successful recovery.

The existing Windows native job includes the new regression module. The complete
PostgreSQL job collects it through its existing suite-wide command. This adds
coverage without changing job deadlines, runtime owners or admission policy.

The corrected actual run (`continuation-20261008-14/root/preserved-v4-pg-02`)
passed the single financial-owner lifecycle case. It used a later native bar for
the explicitly synthetic entry, retained the genuine scorer's result, preserved
the fixed parent, exercised pause/resume and subsequent baseline discovery, and
reopened through the original state and proposal owners. Journal prefix,
reconciliation, original account controls and twenty-slot capacity assertions
passed. Before/after audits matched all 268 Python source/test files, retained
the preexisting failed database state and found no other clients or schema
changes; the exact QA server was stopped.

The separate native/static pack passed 54 tests and skipped 28 explicitly
PostgreSQL-dependent cases. Ruff, formatting, Windows mypy and diff checks
passed. The earlier failed run stays separate. These checks do not establish
prospective coverage, real-time model coexistence, profitability or qualification.

This source-only child of PR86 keeps model admission, storage and ownership
unchanged. It does not install/restart Q-Trades, dispatch a tokenizer/model,
acquire market data, activate research, reset an attempt or change a financial
rule. The accepted installed rollout receipt remains a separate outcome.
