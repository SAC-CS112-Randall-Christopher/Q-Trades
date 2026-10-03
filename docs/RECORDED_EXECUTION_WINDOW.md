# Finite original execution evidence

The first inspected unsupported transition occurred between two retained paper
decisions: the next record's starting projection included an intervening financial
commit without its decision inputs. The original sampler captures ten seconds in
each 300-second UTC period and study changes. Ordinary financial work continues
outside those selections. Complete candles cannot supply the omitted book,
receipt time, notices, accounting transition or observation.

The repair adds one explicit operator request, disabled by default. A private
data/execution-window-request.json selects every financial tick for one actual
2,700-second horizon. The existing capture queue, per-packet limits, disk/tier
budgets, financial writer and resource-demotion guard remain authoritative.

Request format:

~~~json
{
  "version": "recorded-execution-window-v1",
  "request_id": "operator-window-unique-id",
  "not_before": 1791000000.0,
  "horizon_seconds": 2700,
  "start_grace_seconds": 600,
  "max_records": 10000,
  "max_bytes": 16000000000
}
~~~

The illustrative timestamp must be replaced with an actual future UTC time.
The request is loaded at startup; source installation/restart still requires
the normal approval and updater procedure. Do not arm one in synthetic tests
against the operating installation.

Capture begins only with a fresh recorded BTCUSD book and at least 305
continuous, completed one-minute candles actually available at that decision.
The packet retains the full available warmup and original receipt/availability
times. Bootstrap observations are never backdated. Every complete-window packet
also captures the original typed runtime operations preceding the financial
tick and their source hash. This includes feed-status notices, universe
maintenance, added-bar count and book sequences; their order is unchanged.

A restart, missing financial revision, observation gap over five seconds,
missing causal warmup/book, queue refusal, archive failure or finite-budget
exhaustion makes the request incomplete. There is no snapshot bridge, invented
book or automatic replacement request. execution-window-status.json is also
available through the ordinary evidence snapshot. A captured horizon is marked
captured_pending_reconciliation, not accepted as execution proof.

After genuine elapsed capture, use the existing native engine for a private,
read-only baseline audit:

~~~powershell
$env:PYTHONPATH = '<reviewed-source>\src'
& '<installed>\.venv\Scripts\python.exe' scripts/audit_recorded_window.py '<installed>\data' 'G:\Projects\<new-private-audit-directory>'
~~~

This freezes exact storage references and their original payloads, verifies
source hashes, causal feature reproduction, continuous financial state/revision
and book chronology, replays original tick operations, and compares ordered
events, projection hashes and balanced accounting. It uses finite streaming
budgets; it does not enlarge the existing counterfactual replay limits or reset
candidate accounts between small chunks.

No-trade ticks remain results. Full baseline reconciliation establishes software
and original-paper reproducibility. Representative fill accounting stays
unproven until actual fills are inspected. The source mode stays explicit:
synthetic verification, recorded-paper replay and historical candles are
different evidence. This change confers no strategy edge, language-model
qualification, account capacity, live promotion or operating-research authority.
