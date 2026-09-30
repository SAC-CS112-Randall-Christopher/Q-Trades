# CP11: isolated execution replay

AI Lab > Historical matches now reserves and reopens a finite execution comparison
from a retained decision. Its immutable request freezes the CP10 record IDs/hashes,
source identities, existing configuration, and three predefined scenarios. A
separate local child calls the existing PaperEngine; it has no financial database,
venue connection, provider credentials or arbitrary-code interface. The original
accounts, journal, risk policies and execution profile registry remain untouched.

The baseline must reproduce the recorded financial state hash, exact event order
and individually balanced journal lines before any changed scenario runs. Replay
keeps original order/reservation/partial-fill/fee/precision/minimum/dust/expiry/risk
logic. Each acceptance uses an available, fresh, later book; the original consumed
sequence gate prevents repeatedly filling against the same displayed liquidity.
Original revision/event references link the replay receipt to recorded actions.

Canonical archive serialization sorts object keys, so the recorder now freezes
the original account processing order separately. Older CP10 records retain their
original content. If their original event order cannot be reproduced, the baseline
stays unresolved and changed scenarios are withheld; no dispatch order is inferred
from favorable outcomes. Invalid hashes, missing/future features or books, wrong
source versions, chronology regression and changed same-sequence books cannot
produce a supported execution result.

## Supported slice and scenarios

The user selects one, sixteen or thirty-two retained observations at most.
Baseline replay validates each successive prefix before examining the next one.
A missing/corrupt future record cannot change the reproduced original decision.
The state chain must match exactly except for explicitly recorded `study_bars`
and `book_sequences`, which the normal runtime updates before financial ticks.
An unrecorded funding/control/strategy/position/other state transition ends the
supported slice. Counterfactual accounts continue from one common starting state;
they never jump back to recorded balances or fill through absent observations.

The scenarios are frozen hypotheses:

- **Recorded assumptions:** the original per-account taker profile and configuration.
- **Three-second delay:** at least three seconds before later-book acceptance,
  preserving the original fifteen-second order expiry and gap handling.
- **Condition cost stress:** if any currently observed book has spread >=10 bps or
  either side's visible depth <100 USD, all profiles for that tick use at least
  five basis points of adverse slippage and at most five-percent participation.

Changing profiles occurs only in the owned child. The server's original registry
is unchanged. Thresholds and delays are modeled research assumptions; they are not
measurements of venue behavior. The September 30 refresh of the official
[Binance.US fees](https://www.binance.us/fees) and [API contract](https://docs.binance.us/)
supports the existing public fee scenario and observed symbol filters, but supplies
no private account commissions, broker acknowledgments, queue position, own-order
impact or authority. USD fee currency remains an explicit original assumption;
unsupported base/BNB currency is not silently converted. Maker/queue comparison
remains unsupported because the required evidence is absent.

Fees and adverse execution are embedded once by the engine. Net slice account
values are never charged those costs again. The comparison preserves funding,
open/pending exposure, unavailable valuation, additional fees and embedded drag.
Both zero-fill and rejected/no-trade slices remain useful retained results. A
later positive market move does not create an executed trade or realized P&L.

## Paths, attribution and limits

Observed bid marks supply favorable/adverse excursion, observed holding time and
profit given back within the retained slice. Closed trades include their actual
engine holding interval and already-net P&L. A path that started before the slice
is explicitly incomplete. Between-book extrema, stop/target order inside a candle,
continuous horizon coverage and own market impact stay unknown. Replay cannot
turn CP10's candle-only market labels into executable-return labels.

Remaining opportunity begins no earlier than a usable local result, its expiry
and a supported subsequent book. The finite slice does not establish a continuous
45-minute action horizon, so that executable horizon return remains unavailable.
Source, inputs/features and matching actions are measured; delay/condition stresses
and interacting sizing responses are modeled. Data, recognition, retrieval,
forecast, costs/delay, execution and sizing/exit can have multiple possible causes.
The receipt retains that unresolved residual rather than claiming a unique causal
decomposition or strategy advantage.

## Persistence and optional resource boundaries

The replay registry is separate from the financial journal and CP10 archive.
It retains up to 128 attempts, with eight queued/capturing/running requests, a
sixteen-MiB input slice, a 512-KiB result and a 64-MiB SQLite physical budget.
Protected content admission reserves room for results and metadata. Input IDs and
hashes are pinned in CP10 and copied into the immutable replay request. Capacity
refuses optional new work; no experiment or financial history is evicted.

Requests are idempotent: retries reopen the same plan/source/result; changed
requests cannot overwrite that identity. Queued inputs survive restart. An
interrupted capture or child becomes a retained interrupted/failed attempt.
Results and input/plan hashes are checked on reopening, with missing/corrupt
receipts explicitly unavailable. Normal UI history pages conserve membership.

Replay shares the existing numerical research allowance: one child at a time,
two logical processors and Windows IDLE priority, no GPU or paid calls. The
supervisor observes RSS every 100 ms and stops its own child for observed memory
>256 MiB, wall time >25 seconds, shutdown or protected paper/resource pressure.
Those sampled limits are not a claim of an instantaneous OS memory ceiling. It
never stops the paper worker, ArcGIS or model runtimes. Each attempt retains wall
time, observed peak RSS, CPU/throughput where available and zero marginal paid cost.
Repeating an input adds no independent market sample.

## Verification

See `reviews/cp11-execution-replay/README.md` for focused/full component, native
workload, ordinary browser and hosted stages. Source/synthetic proof, approved
merge/install, real execution coverage and prospective 28-day market/account
acceptance remain distinct. CP12's estimator must decline unsupported executable
labels; CP13-CP16 preserve the hardened roadmap, original controls and live boundary.
