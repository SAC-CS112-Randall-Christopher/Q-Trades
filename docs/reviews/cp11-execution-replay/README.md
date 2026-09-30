# CP11 execution replay review

Parent: CP10 draft #16, e009347a8b54fa966767712e0aed1ac900089feb. The exact parent
Windows-native run [36673024899](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/36673024899)
passed with **195 tests and 33 database skips**, plus the dashboard build. This is
separate from CP10's local **420 tests with no skips** and finite actual-host proof.

CP11 uses the same deterministic engine in a credential-free child and freezes
source/input/configuration before execution. Local comparison cases reproduce
state/events/journal balance, partial fills and modeled delay/cost behavior, and
retain failed inputs/source reconciliation, expired orders, future-prefix changes,
resource interruptions, restart, immutable retries, corruption and capacity.
The final local PostgreSQL suite passed **432 tests, no skips, 89.92 seconds**.
Lint, strict types (53 source files), and the production dashboard build passed.
The build receipt remains local; native measurements are in
[`finite-workload.json`](finite-workload.json), with browser observations in
[`browser-checks.json`](browser-checks.json). Exact-head hosted verification is
pending at publication and must be recorded separately.

All native cases reconciled sixteen original decisions and preserved the source
financial projection and balanced journals. The one/ten/twenty actual-account
cases took **0.839 / 1.121 / 1.239 seconds** wall time, with sampled peak child RSS
**34.58 / 37.50 / 41.26 MiB**. The twenty-account compute phase took 0.526 seconds
and 0.453 CPU seconds, or 30.41 supported ticks/second. The observed OS limit was
two processors and IDLE priority; no GPU or paid provider was used. RSS is sampled
by the supervisor, not an instantaneous OS-enforced memory guarantee.

The native high-depth, narrow-spread fixture did not cross the condition-cost
threshold. A separate focused low-depth case exercises the changed cost path.
These measurements establish finite synthetic software behavior, not representative
market performance or an economic benefit. Repeated replay adds zero market samples.

The ordinary browser selected a retained decision, launched sixteen decisions,
refreshed the result, and reopened the same immutable request after a page reload.
Whole-account comparisons explained pre-existing exposure and closing costs already
included in liquidation values. A declared synthetic baseline-mismatch injection
withheld alternative outcomes and kept unresolved attribution visible. At archive
capacity, another one-decision run completed while all six QA accounts remained
visible. After stopping the owned QA server, history reported unavailable and the
selected failed receipt remained readable. Screenshots are synthetic and include
`reconciled-comparison.png`, `synthetic-replay-at-capacity.png`, and
`unresolved-baseline.png`; the first was captured before the explicit data-mode label
was added. The later screenshots verify that label and the guarded failure display.

The original focused failure is retained locally: serialization lost account
iteration order. CP11 now freezes the pre-tick dispatch order explicitly. Older
immutable CP10 records are never changed; unsupported reconciliation withholds
changed scenarios. A separate fixture failure used nonexistent campaign parameters;
its one-account receipt and original launch transcript remain under ignored `data/`.
The corrected builder uses the existing fourteen-member campaign: the actual
twenty-case retains six original account types plus fourteen synthetic members;
one/ten cases project a disposable QA subset. Actual counts are asserted.

Every native workload uses the owned loopback PostgreSQL cluster on port 55633,
disposable schemas and synthetic books. The child has no PostgreSQL connection and
must leave the source projection/journal unchanged and balanced. Replays do not
establish live fills, real feed latency, after-cost economic advantage or new
independent samples. All public receipts and screenshots contain synthetic data.

CP11 source is not installed. The original paper app remains on main cb699456 with
its six accounts/history. Exact-head CI, merge/final-main and installation must be
observed separately; real horizon coverage and the 28-day policy remain unproved.
