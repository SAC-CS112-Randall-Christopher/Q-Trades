# CP8 integrated acceptance receipt

Local full suite: **368 passed, no skips**, 71.42 seconds. The combined risk,
campaign, PostgreSQL, streaming and new resilience checks had **66 passes**.
Whole-tree lint, 46-module type check and production dashboard build passed.
Five normal-browser checks covered campaign launch, failure/pause, recovery without
new funding, retained numerical/no-promotion evidence and exports. A first export
check ran before selecting the retained receipt after reload; selection exposed it.
A rapid follow-up account action correctly rejected an old control version; the
operator refreshed and retried. This UX friction remains an audit item.

The predeclared twenty-account, busy-research soak ran **1,200 ticks in 301.52
seconds**. Commit p95/p99 were **22.84/33.48 ms**, dispatch lag p99 0.59 ms,
queue peak one; parent peak RSS 62.18 MiB, growth 0.66 MiB, CPU 3.93% of one
logical processor. The independently pinned numerical load completed 3,177 fixed
synthetic fits, peak RSS 58.31 MiB. Reconciliation balanced. Paper journal growth
was 1,761,280 bytes; the 5,062,656-byte whole QA database growth also includes other
development schemas. These are finite synthetic local measurements, not market
network latency, ArcGIS latency, 24/7 operation or independent financial returns.

Generated disposable PostgreSQL schemas verified exclusive-writer rejection,
an actual child exit (17) after committing campaign funding but before acknowledging
it, restart/retry without duplicate funding, and pg_dump/pg_restore into a generated
database with exact state/journal hashes. The operating database was untouched.
Unit/component faults additionally cover rollback, immutable journals, stale/
duplicate/reordered observations, disconnect/time handling, inference outage,
disk-pressure research yielding, cancellation, timeout and memory pressure.

The process audit reproduced a Windows virtual-environment redirector: launcher
PID 30024 differed from worker PID 46376. Supervision now launches the resolved
base interpreter with only source/pinned dependency paths. Its actual worker PID,
IDLE priority, at most two processors and measured RSS are verified. Cancellation
and memory accounting therefore target the real fit process. This is containment
for fixed trusted numerical code, not an untrusted-code security sandbox.

CP7 hosted run **36638202234** passed **139 tests / 31 database skips** at edc9ddb.
CP8's exact-head hosted check is separate from this local database proof. Retained
JSON receipts record scopes and the source parent; the final audit will repeat the
capacity/soak with exact committed driver and implementation hashes after changes.
No merge, installation, live order, paid call, original-trial reset or model/GIS
configuration change occurred.
