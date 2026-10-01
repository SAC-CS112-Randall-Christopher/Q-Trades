# Integrated audit repairs: LLM-F1–F7

All seven findings are repaired within their original dependent draft PRs #29–35.
The audited `446bd3193e48b1d47a275c160ae5c3b907a7c3b5` remains an ancestor;
no branch was rewritten and no PR was merged or installed. This is software
acceptance. Actual current-contract model qualification and CP18's qualified
proposal → ordinary mature outcome → supported follow-up remain unestablished.

Final full-tested source: `6b5a9263b41eb0f23d0440b492a450d305d162c1`.
Finite-load source: `b520a4c24f225f870c19e5f88b00fa2c7a7c9220`.
The intervening changes correct only preview imports and the QA helper's reuse
of an existing frozen storage plan; `src` and `apps/web` are identical at both
heads. Subsequent delivery changes are documentation and public receipts only.
Exact draft heads and hosted delivery checks are recorded in the issue/PRs.

## Repairs and acceptance

| Finding / owning draft | Implemented behavior and verification |
|---|---|
| F1 / #34 | Fresh authorization, expiry, allowance debit and claim commit share one immediate transaction. Revoke/claim and expiry-after-debit races use the actual HTTP handler. Already committed delivery cannot recall bytes in flight. Archived external reservations still exhaust the same hourly budget. |
| F2 / #31 | A changed, explicitly offered closed-bar or mature-outcome dependency atomically exchanges a waiting predecessor for its successor. Eight occupied slots resume without raising the limit; failed creation rolls back the predecessor, and unchanged inputs do not invoke another model attempt. |
| F3 / #32 | Full artifacts/methods remain retained by verified hash; role packets contain bounded support, limitations, costs, diagnostics and detail references. Normal 12/128-row memory, reviewer, follow-up and lesson packet construction passes the actual 8192-byte conservative adapter preflight, including a 500-character ASCII question. Actual inference is stopped before resource observation/network; this proves packet compatibility, not model quality or tokenizer limits. |
| F4 / #29 | Reconciled, retired cash-only results use labelled final historical accounting. An ordinary losing trial reopens a day later at net −$0.6331190670. Active/uncertain positions still require valid current marks. |
| F5 / #33 | Immutable first-known content and durable last-successful-check time are distinct. Unchanged refresh reuses the verified original archive; cross-connection leases prevent duplicate acquisition. Initial/24-hour/one-second-later reproduction now makes two fetches rather than three. |
| F6 / #30 | At most 512 full hot tasks continue into verified G: archives with searchable paged history. 529 normal sequential software questions and 4100 request identities retain original details and restart correctly. All attempt status, endpoint counts when present, conservative reservations, lessons and disclosures survive archival; physical registry/G: failures remain explicit. Cold local/external cost and unknown paid billing are included downstream. |
| F7 / #30 | Immutable confirmed rejection permits Edit, Discard or a new retry identity. Unknown acknowledgment freezes the original request for exact reconciliation. Actual HTTP races and normal browser reload/retry checks preserve one accepted task per request. |

## Observed gates

Complete native Windows / CPython 3.12.14 / owned PostgreSQL 16.2 run:
**668 passed, zero failed, zero skips in 231.81 seconds**. Whole-repository Ruff
passes; strict Windows mypy passes **84 source modules**; TypeScript/Vite passes
with **1926 modules** in 1060 ms. Mypy/build ran at `5241d4d` with product source
identical to the final full-tested head. The final source's hosted Windows run
[36939465806](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/36939465806)
succeeds with its selected **361 passed / 127 conditional skips** in 328.16 s.
That hosted selection is separate from the full native run with zero skips.
See [audit-repair-software-checks.json](audit-repair-software-checks.json) for
exact source identities, hashes, stages and limitations.

The first integrated native rerun retains **664 passed / 4 failed** in 235.04 s.
The unchanged affected file reproduced all four failures. Its test setup tried
to complete an ordinary task using its obsolete idea-stage snapshot after it
had reached review; the new stage fence correctly refused. The test now rereads
the current task and asserts completion without changing that product fence.
The affected selection then passes **35 tests** in 26.29 s and the preceding
complete rerun passes **668** in 232.80 s. Both preview startup failures also
remain retained: missing script import path, then an 8-MiB helper plan conflicting
with the preview's already frozen 16-MiB plan. Reusing the existing plan fixes
the helper without increasing its budget or weakening validation. Final preview
seed acceptance passes **8 tests** in 6.85 s before the final complete run.

All **eight predeclared 30-second finite cases** pass: one/ten/twenty accounts
idle or with the fixed numerical child, then twenty accounts idle or with scoped
reads. Every ledger is balanced. Worst financial p95 is **51.126 ms**, below the
unchanged 100-ms limit; the twenty-account numerical case is **47.1933 ms**.
Scoped-read overview maximum is **4823 UTF-8 bytes**. Limits, exact samples,
source hashes, RSS/CPU/queue measurements and read scopes are in
[audit-repair-finite-native.json](audit-repair-finite-native.json).
These generated cases exclude actual busy LLM work, use small owned G: fixtures,
and do not establish 100-GB throughput, browser paint latency or 24-hour reliability.

Normal browser checks use a clearly labelled **synthetic** ordinary memory trial
with three answer stubs and accelerated inconclusive maturity. No actual model
or public-provider requests occur. Invalid-parent Edit/corrected Save, separate
Discard, full-eight queue retry after an owned slot release, lost-success
acknowledgment/reload/exact reconciliation, history search, cold outcome/lesson
reopen and all twelve paged training rows pass. Reconciliation preserves exactly
**11 retained questions / 3 accepted request IDs**, with identical IDs before
and after. At 390×844, document/body/main widths are all 375 CSS pixels, with
internal table scrolling and no page overflow. The viewport is reset afterward.
See [audit-repair-browser-checks.json](audit-repair-browser-checks.json).

The owned preview exits gracefully by verified process identity. The normal UI
then displays Disconnected and labels retained observations historical. The
installed paper listener and GIS listener retain their original process IDs.
The read-only installed check at **2026-10-01 23:21:06 UTC** reports running,
fresh, error-free paper work and a balanced journal; optional research remains
constrained, engine p95 **156 ms**, commit p95 **125 ms**, cooldown **300 s**,
and no dedicated QA model listener. No guard waiver or installed restart occurred.

## Remaining actual proof

Actual v5 qualification, qualified-model CP18 completion, matched qualified
A/B/C/D quality/cost and subsequent economic effects remain unresolved. Historical
scores and synthetic receipts do not satisfy them. Current qualification still
requires the independent development screen and each role's complete 36-case,
three-seed assessment, at least 34 correct and zero critical violations. The
new compact encoding is included in the contract digest
`71f90342b3781819e690cf9bb8890a750e97a34b3818fb1a8d04b2324682b7f5`;
earlier contract scores cannot be reused. SEC/native provider access and the
absent authorized Crik bridge retain their separately documented limitations.

Screenshots are unedited captures of the owned synthetic preview:

- [Explicit synthetic source and archived task](audit-synthetic-cold-source.png)
- [Ordinary inconclusive comparison and supported follow-up](audit-synthetic-cold-outcome.png)
- [Confirmed rejection recovery](audit-recovery.png)
- [Narrow retained task](audit-mobile.png)
- [Disconnected historical observations](audit-disconnected.png)
