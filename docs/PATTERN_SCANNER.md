# Native candle scanner — goal #66

Chris requested upfront historical analysis of eligible USD crypto markets,
followed by alerts and immediate candidate evaluation. The declared scope is
365 days on native 5m, 15m, 30m, 1h and 4h candles, every detected historical
support/resistance level, and reasons for an alert's current eligibility.
The existing Markets workspace owns the interface; ExperimentLab owns the
cooperative background work and its existing registry owns saved progress.
Orders, accounts, model requests and strategy activation are separate owners.

## Source and observation contract

The current universe's USD spot, status, volume, activity, spread and freshness
screens supply the roster. A campaign freezes selected markets, the observed
roster, source/version digest, storage-plan digest and time cutoff. Selection
can cover the whole eligible roster within the existing 2,000-market discovery
bound; it is not limited to the six markets receiving detailed live feeds.
Campaigns remain bounded at 32, and all markets/scopes retain explicit progress.

The public venue's native interval API supplies actual OHLCV and original rows.
[Binance.US's candlestick contract](https://docs.binance.us/#get-candlestick-data)
allows up to 1,000 rows per request and identifies candles by opening time.
Completed UTC candles only are accepted. No minute-quote aggregation, missing
candle interpolation, live-trade subscription expansion or synthetic operating
fallback is part of this scanner.

A dense 365-day market has 105,120 five-minute, 35,040 fifteen-minute,
17,520 thirty-minute, 8,760 hourly and 2,190 four-hour candles: 168,630 total.
The native-page lower bound is 172 requests per market. This is a data-volume
calculation, not measured venue throughput or verified full-market availability.
Newly listed markets and missing provider observations remain incomplete.
The interactive chart inspector retains its separate 5,000-candle bound.

Raw pages, their hashes and immutable source references are retained through the
existing research store and quota/protection checks. Processing advances a
durable cursor only after the corresponding bounded work commits. Every
confirmed pivot is retained in the registry; pagination does not discard levels.
Missing intervals interrupt causal indicator/visit continuity. Older levels
remain visible with the discontinuity disclosed, rather than implying a fully
observed path through the gap.

The shared experiment registry keeps its existing 512-MiB physical ceiling.
The external 400/100-GB store is not additional capacity for the registry's
level/event tables. The 2,000-market selection bound does not prove a full year
of every market fits. Optional scanner transactions must preserve registry
headroom for the existing research owners and stop with explicit incomplete
progress before exhausting it. No quota increase, second database or evidence
deletion is authorized by this source proposal.

## Detection and candidate meaning

The initial version reuses the candle tool's strictly confirmed support and
resistance pivots, zone width, causal visits, bounce, breakout and retest
definitions and prior-volume observations. The separate candle-chart inspector
shows 10/50/100 simple moving averages using candle periods in the selected
timeframe; those averages are not scanner entry criteria in this version.
A pivot requires its confirming
closed candles; later observations cannot retrospectively supply an earlier
signal. Pattern/level observations preserve the original source and definition.

An alert evaluates the present screen, freshness and available cost inputs and
retains its reasons. Unavailable information remains unavailable. A detected
pattern is an inspectable structural hypothesis; it has no measured winning
edge until a separately frozen, prospective comparison establishes one after
costs. Historical patterns are not inputs that earlier paper decisions actually
observed. The scanner does not authorize an entry or rewrite a financial rule.

## Runtime and recovery

Preparation freezes scope without running it. Start uses the exact campaign
identity and expected revision. Pause advances revision so a delayed Start
cannot silently reactivate work. Request receipts are immutable and an uncertain
acknowledgment reopens by its original request ID. The UI retains its request
identity across reload and does not automatically repeat a POST.

One cooperative scanner step runs through the existing lab owner; there is no
new scheduler, researcher, serving backend or financial writer. Native requests
and registry/level work are bounded. Dense overlaps remain pending behind a
durable level cursor until all matches are processed; a LIMIT cannot stand in
for completion. Prepared scopes receive continuing completed-candle analysis
alongside historical preparation. A process restart preserves observations and
returns campaigns to paused state. Source/storage identity changes require a
new explicit compatible scope rather than regrading old evidence.

Optional writes borrow the existing EvidenceRecorder's initialized ResearchStorage
under its lock. They cannot initialize another recovery owner while recording
is active. An unready, closed or differently configured recorder refuses the
optional write. Candle-study reopening uses the existing read-only
`reopen_evidence` helper and preserves the exact original receipt digest.
Shutdown waits for the borrowed writer off the async event loop so independent
financial cleanup can proceed. Normal storage quotas, free reserve, volume
identity, retained history and failure reporting remain protected.

## Acceptance ledger

The source lane starts from merged/installed candle PR #79 commit
`f9bd8574f71badf7218ace0952ad2709ac1a7461`. Its reviewed PR tree and resulting
merge tree match. All six exact merged-commit CI jobs passed. Its single approved
updater used the full ExpectedCommit guard and the existing paper task; the
existing Windows launcher opened the dashboard with exit 0. This browser-based
launcher does not complete native desktop goal #65.

The reused rollout collector and individual offline review confirmed unchanged
original financial prefixes (1,619,609 events / 15,196 journal rows), original
account/funding/configuration/contracts, retained evidence, model attempts,
twenty-slot capacity and 400/100-GB policy. There were 1,268 legitimate appended
events and 17 appended experiment events within the scoped role comparison.
All 249 installed-file checks and 15 storage checks passed. The original consumed
two attempts/two allowances were unchanged. Current financial audit was available
and balanced. Strict receipt coverage and direct NAT writer mapping remain false.

Installed-workflow limitations are retained: the finite native handoff observer
failed with `Task action differs.`; its largest sample interval was 47.838 seconds
and it did not verify a new writer. First startup required a natural supervisor
retry. Stop-stage to ready was at most 151.229 seconds, and restart-stage to ready
at most 128.331 seconds; neither is an exact measured interruption duration.
The later 30.047-second recording check passed 7/8 checks, with +282 captures
and +4 queue drops, but its last research-recording state was unavailable.
Installed BTCUSD 5m study #18 retained its original failed/OSError result after
exact request recovery. A subsequently retained atomic recording-status receipt
reported `Capture recovery busy: another storage writer owns this root`.
This identifies a contention condition but does not establish the exact cause
of study #18's class-only error. No operating repeat request or update follows.

The initial matched disposable storage checks passed 35 tests, with two native
PostgreSQL cases deliberately excluded before explicit QA database verification.
The original live-lock constructor failed in the fixture while the repaired
read-only reopening succeeded on the same retained data without changing segment
state or original receipt. Borrowed tool writes reused the initialized owner
without another startup reconciliation; threaded capture serialized correctly.
Independent review found a synchronous shutdown wait; the off-thread correction
and its cancellation/independent-async-work regression were then verified.

The frozen scanner's focused native run passed 17 tests with no failures or
skips. It covers a complete synthetic native four-hour year, five-minute
continuation beyond the inspector's 5,000-candle limit, dense overlapping levels,
native-source rejection, gaps, revision recovery, restart, cancellation, bounded
source retries and protected registry/storage refusal. The affected shared
storage/tool suites passed 126 tests with one Windows symlink-privilege skip.
Earlier failed setup/test runs and their repairs remain retained.

All-source Ruff and strict Windows mypy passed (115 source files). The compiled
dashboard passed its build and 14 disposable browser groups: preparation,
Start/Pause and exact command recovery, paged levels, historical patterns,
prospective alerts/evaluation, original campaign reopening and responsive layout.
The final dense browser scope retained 106 levels across pages of 100 and six;
its partially processed source page still reported zero completed pages/bars.
Those progress counters advance when the staged page finishes, so saved level
counts are separate from completed-page coverage. The prospective alert came
after 2,190 synthetic four-hour bars; the other native frames in that browser
fixture explicitly remained missing. No real venue or financial database was
used. The browser and its owned fixture server closed normally. Earlier browser
failures remain retained, including fixture assumptions about page completion
and support-bounce candle direction.

Independent combined source review cleared the scanner, shared writer repair,
UI and additive CI scope. An additive independent review verified the final
browser artifacts, frozen source/build match, owned cleanup and retained red
runs. The complete native Windows suite then passed 1,999 tests, with one
symlink-creation privilege skip and one existing Starlette/httpx deprecation
warning, in 982.83 seconds. Its explicit disposable PostgreSQL identity was
`qtrades_qa` / `postgres` at loopback port 54544; no operating database was used.
The exact disposable process/data-directory/listener was verified before its
normal stop; no other client connections remained. The owned process and
listener are gone, and all disposable data and receipts are retained.
Exact-head hosted results remain a separate check to record on the draft PR.
Operating installation/activation and a full real year across the eligible
roster remain separate acceptance. No trading value, complete model coexistence,
continuous recording or populated Library/Reviews acceptance follows from
synthetic fixtures. After the scanner is complete, Chris requested investigation
of the expected eighteen accounts versus eight shown; that investigation does
not authorize recreating accounts or restoring financial history.
