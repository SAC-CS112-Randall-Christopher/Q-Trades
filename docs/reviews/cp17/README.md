# CP17 source acceptance

Issue #28 starts from main 6fc72dccb51e07e00b30bd5c880234c13099297b, including merged #27.
The four tools select active or retired accounts, save exact causal inputs, read
permanent event totals, and expose verified captured detail with scoped cursors.
The existing financial engine, writer, protected accounts, twenty slots, prior
receipts and G: temporary/retained tiers remain authoritative.

## Observed verification

- Full PostgreSQL/Windows suite: see the exact source-head PR/issue receipt for final count.
- Thirteen CP17 tests cover 1103 outcomes beyond caches, account/cutoff membership,
  exact decimals/Unicode, more than 5000 receipts, physical journal pressure,
  reader ownership, finalization crash, archive outage, tamper/expiry/checksums,
  cached analogue disclosure and API paging. Hosted selective gate includes this file.
- Real SCRAM check rejects a password-stripped connection, succeeds using the in-memory
  credential for scoped outcomes, verifies repeatable read-only mode, leaves financial
  state/events unchanged, restores QA authentication and removes generated role/schema.
- Browser: all four buttons on selected active/retired identities; 45 permanent
  outcomes page 20/20/5 without overlap; 120 candle/indicator rows page 30 together;
  reload restores account and immutable receipt; unavailable valuation remains explicit.
- [Native receipt](native.json): 20 accounts, 120 actual engine/journal transactions
  per case, 40 concurrent scoped reads with G: archive. Financial p95 24.773 ms,
  query p95 82.931 ms, serialization p95 0.641 ms, compact overview maximum 4828 UTF-8
  bytes (full capture maximum 44465), peak RSS 66.785 MiB, growth 2.223 MiB; balanced.
  These are disposable software measurements, not economic/market or 24/7 evidence.
- Ruff, strict mypy and dashboard TypeScript/production build pass.

## Retained red attempts and practical limits

Original ignored logs remain locally; source/fixture corrections never relabel them green.
An initial full run had 576 passes/1 failure from a future fixture clock. Later full
runs had 577 and 579 passes. Native attempt 1 found the cutoff race under concurrent
paper commits; subsequent attempts exposed missing freshness/subscription/filter
configuration in the measurement fixture. The archive-enabled final measurement
above is a separate green receipt. An analogue fixture initially missed the archive's
sampling window and was corrected before final acceptance.

Retired long-history totals run indexed SQL aggregation, so latency grows with the
selected permanent history. No 100-GB dataset was exercised. Missing G: storage keeps
exact hot receipts and reports backpressure; details never substitute today's values.
The native contract uses no model tokenizer, so model tokens remain unknown rather
than inferred from bytes. Old receipt versions retain their original meaning.

## Integrated audit correction LLM-F4

A retired account with reconciled cash, no holdings, no pending orders and no
execution/accounting fault now reports its known final net result independently
of the current query clock. The reader labels the accounting as final historical
cash and retains the retirement and query times separately. It does not label an
old quote fresh. Active accounts still require current valuation; unresolved
closures, mismatched cash/equity, dust holdings and uncertain orders remain unknown.

The regression runs an ordinary losing trial through actual retirement, queries
it a day later, saves an outcome-review receipt, closes/reopens the journal and
reads the saved receipt through the API. The original failure and subsequent
fixture failure are retained in ignored data/f4-*.txt. This is disposable software
proof; no operating account or historical financial event was changed.
The complete affected native PostgreSQL run passed 50 tests in 25.41 seconds;
Ruff, strict typing for the changed sources and the frontend build also passed.

## Next checkpoint

CP18 must qualify the expanded proposal/tool contract and demonstrate the actual
model-to-comparison-result-to-follow-up loop. A stopped 11435 listener and historical
partial/failing qualifications do not establish readiness. This PR grants no installed
activation, merge, model download, paid call or financial modification permission.
