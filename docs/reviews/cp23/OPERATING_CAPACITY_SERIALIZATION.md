# CP18 operating capacity: observed bottleneck and bounded serialization repair

This is issue #28 operational capacity work. The qualified real-model feedback
cycle and CP23 usefulness remain incomplete.

## Installed stage already accepted

Approved PR #37 was merged and installed at
`17b11e3007becca85c1352fbd8a111bcc72cd98b` through the existing updater. Final-main
Windows checks passed 363 selected cases with 152 conditional PostgreSQL skips;
the separate full native PostgreSQL run passed 696 with no skips. Normal installed
AI Lab activity now shows actual retained market/evaluation/learning dates without
the authentication warning. Operating model research remains disabled/unqualified.

Ordered canonical prefixes of all 722,673 pre-update financial events and 8,202
journal lines match exactly. Original accounts/contracts, existing trial contracts,
configuration, G: identity, twenty-slot capacity, task identity and five unrelated
files are preserved. All 184 checked installed source/dashboard files match main.
See [the exact rollout evidence](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/28#issuecomment-5945941020).

## Fresh inference-off operating observation

The new diagnostic identifies `engine_work_cooldown` as the sole reported admission
condition; free local space and capture health pass. In a two-minute observation,
194 distinct latest-window samples were collected every three seconds. These are
sampled recent work, not every financial iteration. Of these, 69 exceeded 100 ms,
none reached 1,000 ms, and 73 included full capture. Sixteen slow samples did not
include full capture, so optimizing capture alone cannot establish safe admission.

| Work | Median ms | p95 ms |
| --- | ---: | ---: |
| Entire guarded work | 81.713 | 189.863 |
| Financial tick | 0.697 | 1.360 |
| Transaction read/decode | 21.991 | 56.992 |
| Projection encoding | 6.362 | 13.514 |
| Projection database update | 25.457 | 50.171 |
| Database commit | 3.415 | 17.798 |
| Detached before-state capture | 12.244 | 27.394 |
| Full capture completion | 20.906 | 36.476 |

Transaction subphases are nested inside the enclosing transaction. Financial tick
and before-state capture are nested inside calculation. Do not add these twice.
Full capture hashes the after-state and checks/enqueues the complete packet;
it does not make another after-state copy. The phase names and actual source clarify
that distinction from the initial diagnosis wording.

A separate authenticated read-only driver comparison on actual PostgreSQL 18.6
found a 702,343-byte projection: scalar queries took 1.796 ms median, full projection
read/decode 23.784 ms, text transfer 14.159 ms and JSON decoding 8.963 ms. A five-second
whole-host CPU observation ranged from 55.04 to 67.06 percent; this is an observation,
not a new resource budget or permission to run optional inference.

## Bounded source change

Capture now detaches ordinary JSON financial state directly rather than encoding
and decoding it solely to obtain an independent copy. Unusual values, keys, deep or
circular structures retain the original conversion/rejection path. Every account,
trade, parent, trial and other field stays in the complete snapshot.

Projection transport uses compact JSON without altering the persisted JSONB values.
When capture is selected, its existing canonical encoding is produced once for the
database parameter and SHA256. The committed receipt carries that exact projection
hash; capture reuses it. Earlier receipt formats retain their existing hash path.
State and receipt are returned together under the existing writer lock, so an
intervening financial commit or rollback cannot substitute another commit's event
references or hash. No projection cache or history truncation is introduced.

The private retained-state CPU comparison used 40 randomized samples per variant.
Existing selected-capture serialization took 24.503 ms median / 35.373 ms p95;
the candidate took 15.233 / 21.206 ms. Complete decoded values, detached snapshots
and canonical after-tick hashes matched in every sample. An earlier generic copier
was retained as diagnostic evidence and not selected. This is a serialization
comparison, not an installed engine-load result or proof that the guard will open.

The complete whole-work interval, four-of-twenty/100 ms rule, one-second severe
stall, five-minute cooldown, disk/capture gates and full health admission remain.
Inference/waiting stays outside financial locks. No model/profile/qualification
contract, operating account/configuration/G: data or trial horizon is changed.

After the reader rollout, the actual normal development runner waited 600.491
seconds against the full healthy operating guard and sent zero model requests.
Its only row records an uncompleted admission wait, not an incorrect model answer.
Holdout was withheld. The owned empty CPU service was stopped afterward using
verified process/path/parent/start-time ownership; GIS and the paper service were
preserved. This supersedes the earlier stale/error admission blocker, and does not
establish qualification.

## Required verification and operational remainder

New regressions exercise complete nested financial snapshot detachment, original
conversion/error behavior and exact committed hash/event provenance after another
financial commit and a rollback. Existing replay, journal, reader-concurrency,
supervisor, archival, guard and complete native suites remain required.

The final native suite passed **706 cases, zero skips, 259.14 seconds**, using
CPython 3.12.10 and owned PostgreSQL 17.2. Focused financial/capture/replay/reader/
guard coverage passed 40 cases in 15.39 seconds. Ruff and strict Windows-targeted
mypy passed (84 source files). The first focused setup incorrectly assumed an
initial account label field; its five failures were retained privately, the
fixture mutation was corrected to the existing cash field, and the complete
affected group and full suite then passed. Product guards were unchanged.

The first hosted run on `28ab14e` failed with 372 passed, 152 conditional skips
and one fixture-setup error; dashboard steps were skipped. The new test's plugin
registration depended on collection order. Running the paper-store file before
the capture file reproduced 18 passes/one setup error locally. The repository's
explicit fixture import replaces that registration; the identical ordered pair
then passed all 19. The complete native and new exact-head hosted gates are rerun;
the original failure is retained and never relabeled green. Product source is
unchanged by this test-registration correction.

The new repair stays a bounded draft until its own source and hosted checks are
complete and applicable merge/install authorization is established. Its installed
capacity effect remains unmeasured. Current role qualification still requires both
independent 4/4 screens, then 36 completed cases per role over three fixed seeds,
at least 34 correct and zero critical violations. The first actual paper loop must
use the normal frozen horizon and genuinely observed maturity, followed by a
supported new experiment or specific resumable wait. No guard bypass or test clock
can substitute for these stages.
