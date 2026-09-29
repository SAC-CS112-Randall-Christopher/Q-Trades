# CP3 implementation review — September 29, 2026

## Outcome and source

CP3 launches and manages one ten-account paper campaign alongside the six retained
original/trial/universe accounts. Each has separate cash, reservations, inventory,
fees, losses, strategy/cost assumptions, controls and journal records. One shared
observation stream and the existing exclusive financial writer remain authoritative.
The normal UI includes launch, ten-account overview, selection/inspection, individual
and global entry controls, processing recovery, hard-stop refusal and readable paged
account history. Campaign costs/strategies are frozen at launch. Unknown operating
cost remains unknown; $50/$100 initial funding is a counterfactual declaration.

Base: CP2 `d88ef0022eeab9b59796813807a5beaf49065c7c`, draft PR #5. This is an
implementation/source/behavior review by the implementing agent, not an external
audit. The final source hashes are recorded in `provenance.json`; Git's resulting
commit identifies the submitted draft. No merge, native update, original trial
modification, local-model call, GPU change, new market connection or live order was
performed. The GitHub repository is currently public; these receipts contain only
synthetic QA state and development checks, never operating journals/credentials.

## Acceptance reviewed

| Roadmap requirement | Observed evidence |
| --- | --- |
| Ten separate financial accounts on shared observations | Engine/database cases exercise own reservations, delayed fills, fees, inventory and realized results at both capitals. The browser launches ten accounts alongside six originals, with mixed $50/$100 funding. Journals reconcile. |
| One paused/failing/underfunded account does not borrow or stop healthy peers | Pause cancels only its buys. Proposed per-account work/events roll back on a processing error; siblings fill/continue. Under-$5 failures retain funding/losses without replenishment. Existing financial corruption still stops the writer. Browser peer failure/stop leaves the selected sibling at its own $100. |
| Duplicate/reordered work and restart do not duplicate funding/fills | Launch payload digest plus durable request identity; control versions; saved browser retry; competing-writer refusal; repeated/reordered book and signal cases; clock rollback; owner close/reopen. A successful commit followed by a lost acknowledgment returns 503, then the same request confirms without new funding/events. |
| Normal UI completes launch, inspection, pause/recovery/history | 13 retained browser checks using the compiled React UI, normal API and TieredPaperRuntime over visibly labeled synthetic observations in a generated QA schema. History reads/replaces bounded pages and retains funding. Worker unavailability disables mutations and hides current marks. |
| Measured one versus ten, with resources/connections/latency/storage | Predeclared four-Hz, 120-tick-per-case bounded queue workload in generated PostgreSQL schemas. CPU, working set, queue lag/depth, decision/commit latency, connection scope, state and table growth are retained. Both cases meet the declared limits. |

## Findings corrected during implementation review

The original campaign implementation was unfinished/uncommitted. `audit-before.txt`
retains **4 failed / 13 passed** at the initial campaign test boundary:

1. Account construction rejected unknown operating cost. Optional/null cost now
   preserves CP2's unknown-versus-explicit-zero meaning.
2. Risk reporting collapsed individual pauses and processing faults into the global
   pause message. Distinct reasons and recovery permissions now remain visible.
3. Reordered observations were filtered for campaign financial work but still reached
   shared economics controls. One durable causal gate now protects valuation,
   orders and comparisons, including conflicting books under the same sequence.

The first complete suite retained **1 failed / 327 passed** in `full-tests.txt`.
Its unchanged options component separately retained **1 failed / 22 passed** in
`options-before.txt`: the spot-isolation check read the default financial schema,
assuming an existing operating `paper_state` table. The test now creates its own
generated spot schema alongside its generated options schema. `options-after.txt`
records **23 passed**. No options runtime/policy changed and no operating table was
created to make the test pass. The final complete suite records **329 passed**,
including the additional lost-launch-acknowledgment case.

The first journal link exposed raw data in another tab. It was replaced before
acceptance with a readable, paged account history in the inspector. Each page
replaces up to 100 events; the permanent journal is not truncated. Database paging
checks preserve exact membership and exclude sibling records.

## Executed verification

- `final-tests.txt`: **329 passed**, no skips, one existing Starlette/httpx
  deprecation warning, on Windows with PostgreSQL 17.2. This includes real database
  transaction/rollback/restart/writer-ownership checks in generated schemas on a
  separately initialized loopback-only QA server. No test read an operating trial.
- `lint.txt`: Ruff passed. `types.txt`: mypy passed for all 38 source modules.
- `web-build.txt`: TypeScript/production build passed at the final history UI.
- `browser-results.json`: **13 checks passed**. `campaign-overview.png` is an actual
  viewport capture of the synthetic campaign, showing a retained hard stop and
  healthy peers. The injected $50-to-$30 loss is QA data, not a trial result.
- The Windows native workflow now selects the campaign engine and database/API
  files. Hosted result is a separate GitHub check; database cases on unconfigured
  hosted runners skip rather than invent a database receipt.
- CP0 updater/startup/health files are unchanged from CP2; unrelated source work in
  the original `C:\Projects\Q-Trades` checkout is retained.

Reproduce using the project's development environment and isolated QA configuration:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
npm.cmd --prefix apps/web run build
.\.venv\Scripts\python.exe scripts/verify_cp3.py benchmark
.\.venv\Scripts\python.exe scripts/verify_cp3.py serve --port 8793
```

`verify_cp3.py` always generates a fresh schema; it never initializes/reads an
existing financial projection. This review used a separate PostgreSQL instance,
not the operating database. The financial fixture and test server were scoped to
the CP3 worktree's ignored `data` directory. Research/model processes were untouched.

## Bounded resource result

Host: Intel Xeon W-2235, six cores / 12 logical processors, approximately 95.7 GiB
physical RAM, Windows 11, Python 3.12, PostgreSQL 17.2. Each case delivers two shared
synthetic symbols at four ticks/second for 120 ticks (about 30 seconds), with
accelerated signal bars to stress journaling. Fixture projections retain exactly
one or ten campaign accounts; setup funding rows remain retained. This is a direct
financial-dispatch workload, not a naturally observed forward strategy run.

| Measurement | One account | Ten accounts |
| --- | ---: | ---: |
| Decision p95 | 0.96 ms | 5.88 ms |
| Transaction/commit p95 | 6.30 ms | 17.67 ms |
| Transaction/commit p99 | 7.31 ms | 26.54 ms |
| Maximum transaction/commit | 10.08 ms | 35.49 ms |
| Queue lag p95 | 0.32 ms | 0.32 ms |
| Observed queue peak | 1 | 1 |
| Peak process working set | 60.86 MiB | 61.28 MiB |
| Working-set growth | 0.56 MiB | 0.14 MiB |
| Journal-table growth | 40,960 bytes | 204,800 bytes |
| Logical state growth | 5,079 bytes | 33,753 bytes |
| New events / journal lines | 22 / 16 | 192 / 160 |
| Fixture PostgreSQL connections / market connections | 2 / 0 | 2 / 0 |

The ten-account process used 1.156 CPU seconds, about 3.88% of one core during its
window. The one-account process-time delta reported 0; that sample does not prove
zero CPU cost. Database-wide growth in `benchmark.json` may include other generated
QA schemas; journal-table and logical-state figures above are scoped to each case.
Both journals reconcile, and both cases pass the predeclared latency, memory and
queue limits in `CP3_PAPER_CAMPAIGNS.md`. No inference or GPU workload ran here.

## Limits and next checkpoint

This supports the bounded ten-account software workflow and controlled dispatch
capacity. It does not establish market advantage, independent discoveries, real
account commissions, live public-feed timing, long-duration reliability, simultaneous
GIS performance or twenty-account capacity. Clones remain correlated comparisons;
returns are not pooled. One campaign remains retained; failed accounts cannot be
deleted/refilled or replaced to erase losses. New campaign scheduling/archives and
protected research qualification remain later work.

CP4 is the durable protected experiment registry and consumed-window rules. CP3 and
the CP0–CP2 draft stack still require review, explicit merges and the authorized
normal manual update before workstation acceptance. The parent roadmap remains open.
