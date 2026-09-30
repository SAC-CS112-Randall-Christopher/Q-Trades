# CP10 durable evidence review

Source base: main cb6994561589433a68eae731e48a2b5a5a86ab81. September 30, 2026 UTC.
This source implements one bounded workflow: existing BTC/USD breakout-v1 prefix,
immutable numerical descriptor, local outcome-blind lookup, separate later market
path, then normal AI Lab reopening. The original installed paper application still
runs the base version; Chris independently confirmed its six active accounts.

The complete local PostgreSQL suite passed: **420 tests, no skips, 83.31 seconds**.
Ruff, strict source types (50 files) and the production dashboard build passed.
Focused storage/descriptor checks include future-prefix invariance, reordered or
conflicting revisions, invalid/flat/gapped prefixes, event-group concentration and
pairwise historical overlap, first-label immutability, removed/rolled-back event
references, payload corruption, capacity, disk pause/resumption and restart.
Focused checks are separate from the full-suite receipt.

The native driver uses the owned disposable PostgreSQL cluster on loopback port
55633 and isolated schemas. Do not start that cluster with the default port. Tests
and workloads never use the original application's schema or account projection.

## Finite efficiency evidence

`finite-workload.json` is the final source-hashed, synthetic 1/10/20-account run on
the actual Windows host: 120 ticks per case, four ticks/second, two symbols, full
decision bundle every tick. The declared limits were combined-loop p95 <=100 ms,
commit p95 <=250 ms, process RSS <=512 MiB/growth <=64 MiB and no archive/queue drops.
All cases passed, financial events/state matched the untraced engine every tick,
and every journal reconciled. The twenty-account fixture has the six original
account types plus fourteen isolated test accounts; actual counts are asserted.

| Actual accounts | Commit p95 | Combined loop p95 | Process RSS |
| --- | --- | --- | --- |
| 1 | 8.151 ms | 64.711 ms | 70.65 MiB |
| 10 | 24.580 ms | 75.688 ms | 72.20 MiB |
| 20 | 36.884 ms | 92.830 ms | 73.83 MiB |

Twenty-account combined p99 was 112.609 ms; commit p99 72.061 ms; archive queue p95
2.106 ms; process CPU 25.35 percent of one core including untraced validation;
archive growth 32.35 MB. CPU/RSS describe this measurement process. PostgreSQL disk
growth is separately recorded. A paired 200-repeat immutable-Bar-copy comparison
preserved the exact inputs and reduced copy p95 from 6.962 to 0.527 ms.

`original-red-workload.json` preserves the failed coarse-clock measurement.
`earlier-optimized-incomplete-count.json` preserves the first optimized run. Both
incorrectly labeled eighteen actual accounts as twenty; their scope corrections
are explicit. Neither provides twenty-account acceptance. Original private launch
failure, suite logs and full receipts remain ignored under `data/`.

These are finite synthetic workloads, not live-feed latency, sustained acquisition,
24/7 reliability, private original-account acceptance or a trading advantage.
Captured real venue data is not included in this public repository.

## Normal browser workflow

`browser-checks.json` records observed checks in the in-app browser against the
production build and a disposable six-account fixture on loopback port 8793.
Historical paths use a deliberately mixed-result simulated clock; the ongoing
paper worker uses synthetic books and fresh actual local times. Screenshots contain
only those fixtures and label them synthetic.

The final UI opened the latest twenty rows and the next twenty without overlap,
reopened and focused a saved decision, reproduced both symbols' book/closed-bar
features, showed four distinct positive/negative historical groups, drilled into
an earlier prefix and its separate negative outcome, and filtered seven later
outcomes. The archive reached 307 rows/63.94 MiB and stopped optional collection;
the financial worker remained fresh and six accounts remained visible. Older
inputs still reopened. After stopping only this owned QA server, refresh displayed
a clear reconnect message while the already inspected prefix/outcome stayed visible.

Images: `historical-neighborhood.png`, `subsequent-outcome.png` and
`retained-after-disconnect.png`. The hostile storage/future-input checks above are
test evidence; browser observations do not substitute for them.

## Hosted and prospective stages

Exact-head Windows-native CI is pending publication of the CP10 draft. Its result
and database skips must be reported separately from the complete local suite.
Merge/final-main checks and installation have not occurred for CP10. Real sampled
coverage, sustained retention, representative market outcomes and the unchanged
28-day prospective account policy remain unproved. CP11 execution replay is next.
