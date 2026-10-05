# RAM-assisted paper capacity — issue #48 / operational CP18 under #28

The human requested spare RAM to let the trained model run alongside paper
processing. The existing owned inference child already performs advisory work
outside financial locks, using CPU float32, two logical processors at IDLE,
a 24 GiB RSS ceiling, an 8 GiB free-memory reserve and a 600-second deadline.
The original actual attempt is authorized and unused: real admission refused
engine-work cooldown before importing/loading weights or reserving work.
Qualification and operating activation remain separate.

## Measured lead and implementation

The authenticated read-only installed observation found approximately 58.7 GiB
available RAM and PostgreSQL `shared_buffers` of 128 MiB. These are observations
at one instant. Dominant projection heap/TOAST cache-hit counters already exceed
99.8%; those cumulative counters do not establish present disk or query latency.
`effective_cache_size` is a planner estimate, not allocated RAM. No database
setting, installed process or account was changed. PostgreSQL documents buffer
allocation and its interaction with the operating-system cache in
[the PostgreSQL 17 resource configuration](https://www.postgresql.org/docs/17/runtime-config-resource.html).

The writer's current approximately 0.9 MB decoded projection is reread and
decoded for every transaction. Retain one bounded serialized committed copy
in the exclusive owner's RAM, with an 8 MiB ceiling. Ordinary readers continue
to query PostgreSQL. Zero-byte/oversized projections use the ordinary path;
no journal or historical evidence is cached or removed by this change.

Each transaction still acquires the existing writer lock and locks the SQL
projection row. RAM is usable only when its revision, `xmin` and `ctid` match
that row; these are short-lived validation tokens, not durable identifiers.
See [PostgreSQL system columns](https://www.postgresql.org/docs/17/ddl-system-columns.html).
A miss rereads the authoritative body. Each hit decodes a fresh detached object,
including PostgreSQL's number normalization; callers cannot mutate the cache.
The original invariant checks, append-only journal and actual database commit
remain mandatory. Publish the new copy only after a successful root commit.

Rollback, uncertain commit acknowledgment, nested transactions, external row
changes, oversize and restart discard or bypass RAM and reload from PostgreSQL.
The capture hash is still calculated from the original complete projection
encoding once. The cache neither replaces durable financial authority nor grants
model access to financial mutation. Admission thresholds, cooldown and capture/
disk gates remain unchanged.

## Verification and acceptance boundaries

Native PostgreSQL regressions cover detached caller state, rollback, actual
same-revision row changes and corruption, outer rollback after a savepoint,
actual commit followed by lost acknowledgment, budget/fallback/restart,
exclusive ownership/readers, numeric representation and exact capture hashes.
The affected store/projection/capture selection passes 53 cases. These are
disposable database tests, with synthetic fills identified as test fixtures.
The source includes the new tests in the existing Windows CI selection and
retains the independent ownership job and dashboard build.

The private benchmark freezes one actual read-only projection, then uses four
balanced blocks (off/on/on/off), five warm-up and thirty measured transactions
per block on owned isolated PostgreSQL. Both arms therefore have sixty measured
transactions. Every resulting state must match the original fingerprint. Work
is a no-op; no events or model answers are generated and logical time is frozen.
It measures projection read, validation, serialization, update and commit, not
the full paper workload, retained-journal scale or simultaneous model serving.
The real projection and raw receipts remain private outside Git.

Final measurement, full-suite and exact-head hosted results are recorded in the
owning draft/issue after completion. Installation requires its own applicable
authorization and preservation checks. Installed acceptance must measure ordinary
paper work at retained-history scale, the unchanged full guard, capture health
and the approved trained-v2 attempt together. RAM improvement alone does not
prove safe parallel inference, qualification, genuine feedback or trading value.
