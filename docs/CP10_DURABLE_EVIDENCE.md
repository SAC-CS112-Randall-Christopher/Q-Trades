# CP10: causal evidence and local timing

The separate `research-evidence.sqlite` archive retains sampled inputs for reopening
in AI Lab > Historical matches in the normal dashboard. It grants no financial authority. The financial journal
and account policies remain authoritative and are not pruned or migrated.

Before acquisition, the archive freezes a 64 MiB physical-admission budget,
20,000-record cap, a 512-episode library cap, the first ten UTC seconds of each five-minute period, and one
broad summary per minute. Changed closed-bar studies also receive decision bundles,
regardless of whether the resulting trade is accepted, rejected or absent. Selection
does not depend on later returns. All retained rows stop at capacity rather than
evicting earlier inputs. Required experiment references can pin an existing ID/hash;
they cannot redirect that reference. An increased budget requires a distinct plan.

The optional writer has eight queued packets, at most 2 MiB each; two places are
reserved against non-decision traffic for decision bundles. Overflow, physical
admission, low disk space and failed storage are explicit. A retained decision
includes its validated visible book, raw update where available, instrument/rules,
execution identity in frozen account state, existing causal closed-bar inputs and
features, numerical quote inputs, observed local trade tape, feed gaps, availability
times and process-session identity. Broad summaries cover ordinary periods between
high-resolution windows. A sampled archive does not establish continuous coverage.

The canonical book feature function is shared by recorded research and prospective
challengers. Closed-bar reproduction calls the existing strategy feature function
at its recorded computation time, retaining bootstrap/staleness/data-fault gates.
Future or stale receipts and a later feature-computation time cannot establish
entry evidence. Prices, quantities and money remain Decimal strings. Older raw
capture still has its disclosed rolling policy; it cannot replace a missing
protected archive.

Tracing records decision-evaluation start, reservation-ready/event emission and
post-transaction commit using one process's monotonic clock. Stream book validation
duration, local receipt age at dispatch, prepare/transaction duration and archive
queue wait are independently labeled. Exchange timestamps retain clock uncertainty.
Unmeasured REST validation timing remains unavailable. Emission is not a broker
acknowledgment, and a rolled-back attempted event is not a committed financial action.

The dashboard opens bounded pages of decisions, coverage summaries and selected
wire observations. It verifies each payload hash before showing a reproduction.
Missing IDs, corruption, unknown feature origins and missing books produce explicit
unavailable states. Input JSON remains local and expands only on request. API reads
use separate read-only SQLite connections outside the financial event loop.

## Historical memory contract

The updated [roadmap and memory addenda](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/1#issuecomment-5903487598)
freeze the first slice to existing BTC/USD breakout-v1: its ten-minute entry
lookback and 45-minute maximum hold. Each episode has a stable content reference,
as-seen cutoff, original units, input/source hashes, availability and expiry.
Ten consecutive minute returns form the local numerical descriptor; an immutable
raw prefix preserves prices, volatility magnitude and measured/missing context.
Flat, missing, gapped, stale and late prefixes remain invalid rather than neutral.
The existing complete trend history is retained for original strategy reproduction.

The initial lookup is exhaustive over at most 512 retained descriptors, using
price-relative basis-point distance with no fitted normalization or time warping.
Five neighbors at most, one per calendar event group and no overlapping historical
lookback/outcome intervals are selected without outcomes. Eligibility uses the
actual descriptor availability and compatible version/instrument/data mode;
post-cutoff labels cannot change selected matches or the saved library snapshot.
Similarity, group counts, recognition confidence and economic evidence are separate.
Recognition confidence is not estimated; CP10 supplies no trading probability.

The same closed-bar opportunity reuses its first episode/reference rather than
multiplying support. Accepted, rejected, unaffordable and no-trade situations share
the selection rule. Fixed time windows and broad summaries also capture background
and fault coverage. Queue omissions are counted; this is sampled coverage, not a
census of all feed events. A late lookup retains its actual availability and expiry,
with the predefined no-additional-signal fallback. It never changes the baseline.

Outcomes mature in separate immutable records after the declared horizon, at most
sixteen per writer batch. The first qualifying subsequent input records a complete
45-minute candle path or an explicit unavailable path. Later corrections do not
rewrite that label; unavailable coverage is retained. Price movement from the
prefix close and OHLC favorable/adverse excursions are market diagnostics, not net
returns. Intrabar order is unknown. Remaining executable opportunity after result
availability, hypothetical fills and realized P&L require CP11-supported evidence;
CP10 does not infer them. This is the bounded delayed-label portion of the joint
CP10/CP11 slice, not completion of CP11's execution scenarios.

The normal UI reopens the as-seen prefix, initial historical neighborhood and
separate later outcome. Earlier matches link to their original prefixes. Saved
receipts do not rerun a provider, retrain a model or mutate the financial ledger.
Exact financial revision/event IDs come from the existing writer after commit;
attempted events removed by account rollback cannot acquire those links.

## Measured efficiency

The original full-copy workload missed its combined-loop p95 limit (109 ms with
the coarse Windows clock). The original red and first optimized receipts also
misreported an eighteen-account fixture as twenty; both remain with a scope
correction and are not twenty-account proof. The corrected builder creates the
six original account types plus fourteen test accounts and asserts actual count.
High-resolution monotonic timing and corrected-count results remain separate.

The optimization copies immutable Bar scalars directly instead of recursive
asdict plus another JSON round trip. A paired 200-repeat same-input check preserved
every scalar and measured copy p95 6.962 ms to 0.527 ms. The final actual
1/10/20-account runs passed the original 100 ms combined p95 and 250 ms commit
p95 limits. Twenty-account combined p95/p99 were 92.830/112.609 ms, commit p95/p99
36.884/72.061 ms. Queue p95 was 2.106 ms, RSS 73.83 MiB, process CPU 25.35 percent
of one core including untraced validation, and archive growth 32.35 MB over 120
forced full bundles. No queue/archive drops occurred; each traced/untraced result
matched and every journal reconciled. CPU/RSS describe the measurement process;
PostgreSQL disk growth is recorded separately, not folded into process CPU.

This is three 30-second, two-symbol, four-ticks-per-second synthetic cases on the
actual Windows host, with a full bundle every tick. It is not public-feed latency,
continuous live capture, a 24/7 soak or proof of a trading advantage. Real sampling
and storage duration must be observed after approved installation. Required input
capacity remains finite and stops acquisition, without deleting old evidence.

## Input permissions and labels

The September 29 review of the [Binance.US terms](https://www.binance.us/terms-of-use)
found limited personal/internal use and restrictions on resale, distribution and
public display. Actual captured inputs stay private and local; published test
receipts contain synthetic fixtures only. This is not a redistribution license or
a legal guarantee about all derived uses. The [official stream contract](https://docs.binance.us/)
defines depth sequencing and trade IDs; the existing adapter still validates and
resynchronizes those inputs. No new endpoint, credential, paid provider or model is
introduced.

CP12 can inspect existing minute-quote coverage offline. These records lack
historical executable books and cannot supply measured executable net-return labels.
Insufficient coverage is a complete research result; price prediction is not
substituted for executable economics.

## Verification scope

Source checks, disposable database/browser checks, a finite synthetic Windows-host
benchmark, approved merge/installation and subsequent real acquisition are separate.
See the CP10 review receipt for observed runs. CP11 extends this evidence into
isolated execution replay; CP12–CP16 remain sequential work. The 28-day prospective
policy and live-disabled boundary remain unchanged.
