# CP18 current installed evidence and explicit projection compression candidate

The activity reader works in the actual application. The qualified real-model
research/feedback cycle and subsequent CP23 sustained/usefulness work remain open.
Issue #28 owns this bounded operating-capacity repair.

## Approved PR #38 rollout is complete

Main and the installed application are `6bfd3cda405644763b7a7b8d5b67f772219315d9`.
The explicitly authorized existing updater completed in 72.0 seconds; its third
normal health probe confirmed the new commit. Final-main [Windows checks](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/37015146206)
passed 372 selected cases with 153 conditional PostgreSQL skips. The separately
recorded native PostgreSQL source run passed 706 with zero skips in 327.15 seconds.
Ruff, strict Windows mypy and the 1,926-module frontend build passed for that change.

Ordered canonical prefixes for all 771,895 pre-update events and 9,154 journal
lines match exactly. Original six contracts, eight account identities, existing
trial/parent contracts, configuration, G: identity, twenty-slot capacity, task
identity and five unrelated files are preserved. All 184 checked installed source/
dashboard files match main; the financial journal is balanced and the service fresh.

The normal installed AI Lab -> Local model research screen distinguishes actual
market observation, paper processing, signal, replay, outcome availability and
historical learning timestamps from its query time. The durable-query warning is
absent. In-app browser execution was unavailable in this session; a fresh isolated
headless Chrome/Playwright context exercised the actual service, saved screenshots
and closed afterward. No original user browser session or application mocks were
used. Research remains disabled/unqualified with zero retained role questions.
See [the exact issue receipt](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/28#issuecomment-5954763031).

## Current inference-off capacity

A new five-minute observation samples the latest work window every three seconds:
353 distinct work entries, 166 exceeding 100 ms, zero reaching one second.
This does not count every financial iteration. Disk/capture/full health pass;
`engine_work_cooldown` alone holds admission closed. No model requests were made.

| Work | Median ms | p95 ms |
| --- | ---: | ---: |
| Entire guarded work | 97.431 | 162.603 |
| Financial tick | 0.944 | 2.185 |
| Transaction read/decode | 38.029 | 50.407 |
| Projection encoding | 9.031 | 19.852 |
| Projection database update | 32.042 | 54.732 |
| Database commit | 3.419 | 19.451 |
| Detached before-state capture | 9.252 | 20.580 |
| Full capture completion | 11.802 | 27.071 |

Subphases overlap the transaction/calculation; do not add them twice. These new
samples and the earlier pre-update measurements have different host/state conditions
and are not a controlled speed comparison. PR #38 did not establish safe admission.

Authenticated read-only actual PostgreSQL 18.6 queries found a 759,991-byte text
projection: median scalar 2.394 ms, full read/decode 28.906 ms, text transfer 19.313
ms and JSON decoding 9.599 ms. Windows thread CPU time was too coarse for a useful
phase estimate; wall timings use the precise counter. A different existing decoder
saved only about 2.5 ms in the actual driver path and was not selected.

## Bounded disposable comparison and selected change

Forty samples per arm were randomized under one fixed retained-size workload in
fresh disposable PostgreSQL 17.2 schemas. Normal no-op PaperStore transactions used
initial synthetic financial accounts plus a private retained-size payload. No
operating accounts or history were written. Complete projection values/hashes and
synthetic journal reconciliation passed; these are performance/equivalence probes,
not maturity, model or installed-load evidence.

| Variant | Transaction median ms | p95 ms | Stored bytes |
| --- | ---: | ---: | ---: |
| Ordinary writer / pglz | 66.041 | 111.151 | 202,756 |
| Candidate detached cache / pglz | 68.385 | 100.229 | 202,756 |
| Ordinary writer / LZ4 | 57.169 | 97.977 | 190,860 |
| Candidate detached cache / LZ4 | 52.748 | 89.434 | 190,860 |

The earlier two-arm cache probe was 87.435/135.185 versus 79.345/112.968 ms. Its
later modest/variable benefit does not justify selecting the cache. No cache or
decoder change is implemented. The ordinary LZ4 arm reduces median projection
update from 29.343 to 16.511 ms in the four-arm run, with identical 764,479-byte
complete text values. Actual installed guard admission remains unproved.

The source candidate adds an explicit optional compression decision to the existing
updater. With neither compression argument, its behavior is unchanged. An
authenticated read-only preview validates current metadata, actual build capability
and initialized projection before stopping the app. Apply runs only after the
normal verified shutdown, refuses the ordinary financial writer's advisory lease,
takes a bounded table lock, rechecks metadata and changes only `paper_state.body`'s
future-write compression. The exact stored text hash, revision, size and current
compression must remain unchanged during that metadata transaction.

[PostgreSQL documents](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DESC-SET-COMPRESSION)
that this metadata change does not rewrite existing rows; future values use the
selected method. LZ4 requires build support. The actual installed PostgreSQL 18.6
read-only preview passes for `default` -> `lz4` and confirms currently stored pglz.
The utility can restore `default` with an explicit expected `lz4`; ordinary future
writes then resume the configured default. Neither direction rewrites journal,
events, history, account parameters, G: policy, trial horizons or current JSONB values.

No apply, new installation/restart, operating research activation or model call has
occurred for this candidate. Source/QA and exact-head hosted proof are recorded
separately before requesting its concrete merge/install/compression decision.

## Source verification

The corrected focused selection passes 57 native/actual-PostgreSQL cases in
73.44 seconds, with one existing deprecation warning. It covers preview during
active financial work, writer exclusion, complete typed projection and journal
preservation, future ordinary LZ4 writes, rollback to default, unsupported schema,
bounded reader-lock failure/lease release, unsafe input and credential redaction.
The existing Windows updater tests also cover default behavior and optional
preview-before-stop/apply-before-start, failed preview, failed apply and missing
reviewed expectation using actual disposable Git/robocopy and mocked task/native
commands. These mocks do not establish an installed compression rollout.

The initial focused run retained 27 passes and one fixture assertion failure:
an apply failure correctly left copied source installed and the service stopped,
but the old assertion expected source copying had not happened. The corrected
assertion accepts the existing updater's actual ordering and still requires the
service stopped/disabled, no health-success claim and all sentinel data unchanged.
Whole-repository Ruff and strict Windows mypy pass, 85 source files. Full native
source `41278649fc341bba04b45c16e28bf3ddc5bd9458` passes **721 tests, zero skips,
278.76 seconds** on Windows/CPython 3.12.10 and disposable PostgreSQL 17.2. The
frontend build passes, 1,926 modules. Its exact source-head [hosted gate](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/37023250745)
passes 378 selected cases with 162 conditional database skips in 152.75 seconds.
Later receipt/documentation commits keep the same tested product source; their
exact final-head gate is recorded in draft PR #39 and issue #28 before approval.
See [the public source receipt](projection-compression-software-checks.json).

## Applicable approval and acceptance

After source/QA and final-main gates, the proposed existing-updater command is:

```powershell
.\scripts\Update-QTrades.ps1 -PaperProjectionCompression lz4 -ExpectedPaperProjectionCompression default
```

This command needs the owner's explicit approval for the new merge/install/restart
and this narrowly scoped database metadata change. The fulfilled PR #38 approval
does not authorize it. Before/after history/configuration/G:/task/source preservation
and normal installed UI/API acceptance remain mandatory.

Invoke this new option from a clean checkout refreshed to the approved merged main.
An older updater script cannot bind a new parameter before its own internal fetch.
The existing separate updater checkout can fast-forward from installed main; do
not run from the feature branch or overwrite installed data/configuration.

Then observe the original full guard through its real cooldown, without changing
four-of-twenty/100 ms, the one-second stall, 300-second cooldown, disk/capture or full
health admission. If capacity opens, run current independent 4/4 development for
each actual role, then 36 completed cases per role across the three frozen seeds,
at least 34 correct and zero critical violations under the approved sequential CPU
profile. No inference/waiting occurs inside financial locks; GIS/11434 is preserved.

The authorized separately owned paper demonstration follows qualification through
the normal AI Lab question/evidence/proposal/method/review/account workflow and
genuine frozen elapsed maturity, with one supported successor or resumable wait.
Original operating activation stays separate. CP23 sustained housekeeping/recovery
and matched A/B/C usefulness are unperformed; prospective account benefit is unknown.
SEC native access and actual Crik connectivity remain outstanding issue #28 scope.
