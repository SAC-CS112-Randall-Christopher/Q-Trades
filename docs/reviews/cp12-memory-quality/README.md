# CP12 memory-quality review

Parent CP11 draft #17, 752dd14. Its exact-head Windows-native run
[36680786710](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/36680786710)
passed **207 tests, 33 database skips and the dashboard build**. Its separate full
local database proof was 432 tests with no skips. CP11 is not installed.

CP12 implements the bounded shadow comparison, supported linked-fill target
boundary, training-only normalization, chronological calibration/protected scoring,
unfamiliar/weak/invalid/late fallback, retained B/C artifacts and cost/contribution
limitations through the existing registry, adapter and normal UI. It does not
establish a qualified memory account or whole-account advantage.

Initial focused failures are retained under ignored `data/`: a test used the claim
receipt instead of the full frozen job, another assumed the evidence API wrapper
had a top-level timestamp, and a long-jump fixture retained stale candle features.
The latter was rebuilt with valid as-seen bars rather than weakening replay. The
final linked-fill fixture includes the original intent, later buy/exit fills and a
separately observed mature horizon; missing maturity/corrupt replay stay unavailable.
The browser found date-input event handling and a missing existing local-operator
header; both were repaired before the successful normal workflow. No security gate
was weakened. A request/body is saved before submission for immutable uncertain retries.

Final local database suite: **443 passed, no skips, 93.40 seconds**. Lint, strict
types (55 source files) and dashboard build passed. Native
[`native-workload.json`](native-workload.json) observes 0.843 seconds wall time,
33.49 MiB sampled peak child RSS, two OS processors/IDLE and zero GPU/paid calls.
Two hundred repeated local predictions measured p50/p95/p99 **0.283/0.486/0.544 ms**;
repetition adds no market samples. Its scalar target fixture is explicitly synthetic,
separate from the focused intent/fill/close/mature-horizon engine fixture.

The ordinary UI froze a new protected study, refreshed/reopened its completed
negative result, and retained all **295 opportunities with zero available executable
targets** after the eight-MiB dependency limit. Reload reopened the same reference.
A separate declared synthetic scalar-label fixture was seeded only in the owned
QA registry, then inspected through the ordinary shared experiment list. It retained
twelve training/six calibration/eight test groups and separate B/C artifacts, with
mixed neighboring outcomes and unavailable probability in a sparse calibration bin.
Reload recovered that same artifact without another fit or any funding/promotion.
After stopping the owned QA server, the previous insufficient result remained visible
with a fetch failure. The forced-stop temporary-file/schema teardown was not confirmed;
its owned path and receipts remain private for the integrated cleanup audit. The
original installed application separately passed its read-only exact-main health check.

See [`browser-checks.json`](browser-checks.json), `insufficient-reopen.png` and
`frozen-artifact.png`; all browser data is synthetic. Exact-head hosted checks are
pending at draft publication and must be reported separately.

Public files contain only synthetic/redacted source fixtures. The
original installed six-account paper application remains on main cb699456 with its
full funding/history, model/GIS processes and private configuration intact.
