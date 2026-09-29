# Tiered research and execution

Chris confirmed this direction on September 28: spend more reasoning on improving
strategies, then execute the useful findings quickly with small models and explicit
code. This document records the intended architecture, not a claim that a qualified
LLM harness or trained trading policy is already active.

| Layer | Work | Timing and authority |
|---|---|---|
| Researcher and reviewer | Propose falsifiable improvements, investigate losses, challenge methodology and evidence | Bounded background jobs; four-hour research cadence after qualification. No order, balance or risk authority. |
| Training coordinator and numerical tools | Run a registered experiment, fit numerical parameters on training data, compare later observations after identical costs | Sequential, reproducible jobs. The LLM proposes within the registered space; deterministic tools compute the result. |
| Fast quantitative scoring | Apply a frozen statistical model or rules to current eligible features; rank opportunities and estimate net return/risk | Eventually measured on this machine against the market-update budget. No per-tick language-model request is required. |
| Execution and position management | Check cash, freshness, spread, liquidity, sizing and limits; simulate orders and manage protective exits | Existing deterministic paper engine. Research downtime cannot prevent managing an open position. |
| Small LLM helpers | Summarize recorded events, explain decisions or extract bounded research evidence | Optional and independently qualified. A faster model does not inherit trading permissions. |

The output of deeper reasoning should become a versioned candidate artifact:
hypothesis and evidence references, exact feature definitions and availability times,
model/rule parameters, prediction horizon, immutable cost assumptions, consumed
training/test periods, registered input limits, measured latency and failure behavior.
The currently registered experiment permits only its existing features and horizons;
new feature families or parameter-search spaces need a separate reviewed experiment
version. Generated text or Python is not loaded directly into the trading engine.

Qualification is followed by substantive research checks, chronological validation
on unconsumed data, and a separately governed prospective paper comparison. Evidence
must address after-cost outcomes, drawdown, turnover and operational reliability.
Passing a role-contract test or reducing prediction error is not a promotion by
itself. A candidate cannot raise its own risk ceiling, rewrite failed experiments,
change historical costs, or become the primary trading rule on an LLM's approval.

The three research roles may share weights. Separate instructions are useful for
task separation but do not make their judgments statistically independent. The next
installed candidate is Qwen3 14B in reasoning mode, using the unchanged v3 role
contract and its previously tested 300-second background request profile. Its prior
researcher development median was about 154 seconds, above the 45-second latency
target. Chris subsequently explicitly accepted slow, larger models for training
improvements. The earlier 45-second target therefore is not a selection requirement
for this background tier. Still report the actual elapsed time, timeouts, memory
pressure and impact on the paper worker. The next evaluation retains its already
screened 300-second per-request limit; it is not extended in response to failures.

The numerical preflight already consumed test observations through
`1790595239.9180105`. A future research journal must import that boundary before
testing another candidate. Market collection and the existing deterministic paper
review continue while local LLM qualification waits for available resources.

See [qualification gates](2026-09-28-agent-qualification-plan.md),
[harness implementation contract](2026-09-27-agent-harness.md), and
[preflight evidence](2026-09-28-numerical-preflight.md).
