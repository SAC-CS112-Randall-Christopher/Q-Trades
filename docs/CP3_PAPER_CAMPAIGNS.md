# CP3 — Ten isolated paper accounts

The Paper screen can launch one retained ten-account campaign alongside the original
trial and comparisons. Give each account a distinct name, $50 or $100 hypothetical
capital, one of the three frozen spot strategies, an execution profile and an optional
estimated operating allocation. Blank operating cost is unknown; zero is an explicit
zero-cost assumption. Matching copies prove mechanics and capacity, not independent
discoveries. Their returns cannot be added into a realizable pooled portfolio.

The overview shows all ten accounts. Select a name to inspect orders, holdings, fees,
funding, drawdown, skipped entries, risk status and its paged journal. Whole-account
economics includes the accounts from their next full common comparison window.
Strategy and cost settings are frozen at launch; original accounts retain CP2 controls.

An account pause cancels pending buys while position exits remain enabled. Clearing
it preserves a global pause, hard stops, daily limits, funding and losses. The global
entry control applies to every paper account. A processing failure rolls back that
account's proposed changes and leaves siblings running. Retry processing uses fresh
data and checks the unchanged account invariants; hard-stop recovery remains CP1's
separate action inside the existing loss boundary. Financial corruption of already
committed state still stops the writer rather than being ignored.

All accounts consume one shared set of timestamped BTC/ETH observations. Each owns
its cash, reservations, inventory, orders, fees, strategy, costs, loss reference,
attempt history and entry controls. The existing exclusive writer and transactional
PostgreSQL journal remain authoritative. Launch identity and control versions survive
restart. The launch form retains the same request before dispatch and after a lost
acknowledgment/reload. Retrying cannot add initial funding a second time. A second
campaign or edited configuration under a used launch identity is refused.

Campaign observations use persistent symbol watermarks. Older timestamps/sequences
and changed books under the same sequence are rejected before valuation, fills and
the shared comparison controls. Signal bars cannot move backward. No inference call,
new feed subscription, signing credential or account funding permission is added.

## Verification contract declared before measurement

Use generated schemas on an isolated QA PostgreSQL instance. Browser data is visibly
labeled synthetic; it is not an unavailable-live-data fallback. The normal compiled
UI and API must launch ten accounts, inspect/select them, pause/resume an individual
and global entries, retain them through reload, show a failed account's recovery,
and refuse hard-stop recovery below the existing loss limit. API/database checks
must cover rollback, competing writers, repeat launches/controls/observations,
reordered data, restart and exact account journal pagination.

For the synthetic one-versus-ten financial workload, declare 120 ticks per case at
4 Hz, two shared symbols, one writer and two PostgreSQL connections (writer plus
schema administrator), with no network market connections. Use bounded timestamped
queue delivery. Each fixture projection retains exactly one or ten funded campaign
accounts; setup funding rows remain retained. Accelerated bar signals stress decision
journaling; this is not a naturally observed five-minute strategy run.

Predeclared gates: transaction p95 <= 250 ms, maximum <= 2,000 ms, process working set
<= 512 MiB, working-set growth <= 64 MiB, observed queue depth <= 2, and balanced
journals. Record CPU time, working set, queue lag, decision and commit distributions,
connection counts, journal/event counts and state/table storage growth. This short
controlled workload does not prove 24/7 reliability, twenty-account capacity, live
feed timing, simultaneous GIS workload or profitable trading.

Reproduce with `scripts/verify_cp3.py benchmark` and `scripts/verify_cp3.py serve` in
the project environment after the web build. The script always generates its own
QA schema and never reads or initializes an existing financial projection. Retained
results and the post-implementation review are in `docs/reviews/cp3-paper-campaigns`.

CP3 remains a draft until reviewed and explicitly merged. Installing it uses the
existing manual updater after deployment authorization. The operating trial, model
qualification, CP0 updater and earlier account histories are separate from these
tests; unmerged implementation is not an installed application.
