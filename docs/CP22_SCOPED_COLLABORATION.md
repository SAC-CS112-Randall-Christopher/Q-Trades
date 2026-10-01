# CP22 scoped collaborator workflow

The operator can select a saved role question, issue a short task-scoped credential,
inspect actual ownership/attempts, and revoke access without changing paper accounts.
A contributor claims its granted researcher or follow-up stage, receives its frozen
semantic packet, returns one validated final answer, and reads the recorded result.
The existing local worker computes and archives the method check, requires its local
reviewer, and uses the ordinary inbox/controller/financial engine. External input
cannot approve funding, qualify a role, change policy or bypass capacity.

Source extends the same experiment registry and CP18 task/attempt lease. This is a
local HTTP adapter and disposable PostgreSQL integration proof. There is no callable
installed Crik connector or authorized bridge in this session. A cloud Dot cannot
reach loopback merely because these routes exist. Actual Crik acceptance is blocked;
no bridge, public dashboard, external worker, schedule or paid provider was activated.
CP18's qualified local reviewer is also operationally blocked by the resource guard.

## Interface and configuration runbook

Use the normal selected-question UI or a same-origin local operator call to
`POST /api/research/actors/grants`. The strict JSON body supplies `actor`, one to eight
existing `tasks`, and an explicit `processing_location`. Optional limits are
`lifetime_seconds` (60–7200, default 3600), `output_bytes` (8192–262144, default 65536)
and `requests` (1–100, default 20). The UI grants its one selected task. The random
credential is returned once; only its SHA-256 is retained. The browser keeps it in
memory until dismissed and never writes it to browser storage. The processing
location is an operator declaration, not an attestation of a remote model.

Every contributor request requires `Authorization: Bearer <private credential>`:

| Request | Strict body / result |
|---|---|
| POST `/api/research/actors/tasks/claim` | `{ "task": "role-<32 hex>" }`; frozen packet, contract/hash, claim and expiry |
| POST `/api/research/actors/claims/renew` | `{ "claim": "<32 hex>" }`; current expiry |
| POST `/api/research/actors/claims/release` | Same claim; unknown completion retained, explicit local retry required |
| POST `/api/research/actors/answers` | Claim plus `answer` in the CP18 role contract; one immutable final answer |
| GET `/api/research/actors/tasks/<task>/result` | Granted task stage/reason/result; protected outcome disclosed before delivery |
| GET `/api/research/actors/tasks/maintenance` | Granted task stages and storage state only; no paths, private archives or global account information |

Local operator `GET /api/research/actors/grants` shows scoped grants/budgets without
credentials. `POST /api/research/actors/grants/<grant>/revoke` revokes future access.
An external bearer cannot call those operator routes or any unrelated dashboard,
tool, proposal, financial or filesystem route, even with the operator header.
Additional fields, arbitrary URLs/tools, another task/grant and expired credentials
fail. A contributor cannot retrieve another task by guessing its ID.

Before configuring actual transport, obtain explicit authorization for its precise
connector, network exposure, model processing location and data scope. The adapter
must forward only the contributor allowlist with the research bearer intact; it must
not proxy the dashboard/operator routes or permit arbitrary loopback URLs. Loopback
is the current local operator trust boundary, not a sandbox for an arbitrary program
already able to issue host requests and strip its credential. No bridge setup or
fictional Crik configuration file is prescribed here. Never share operator/financial
credentials. No Decisions endpoint/schema/access/cost is verified or enabled.

If two-hour Crik housekeeping is later authorized, first inspect any existing
schedule, then use only the granted maintenance/status interface and supported
follow-up proposal. Migration/expiry remains with tested local maintenance. External
work has no deletion, loss-history reset, weights, cleanup or policy capability.
Long-lived paper outcomes require a fresh explicit grant after expiry; access never
renews itself for the duration of a trial.

## Ownership, allowances and recovery

LLM-F1 correction: grant scope/expiry/revocation, allowance settlement and claim
reservation now share the registry's immediate write transaction. Renew, answer
and release use the same boundary and re-read the current grant/claim. Rejection
rolls back its debit and mutations. A concurrent revoke either commits first and
prevents the mutation, or commits afterward and releases its committed lease.
An answer already committed remains immutable. A response authorized before
revocation may already be in flight; its bytes cannot be recalled. Subsequent
requests fail and no new lease can escape revocation. No inference or financial
transaction occurs in this registry boundary.

The four added regressions reproduce the original claim ordering through actual
HTTP and expiry during claim/renew/answer settlement. The original source failed
all four (ignored data/f1-original.txt). The corrected actor suite passes all 12
tests on disposable native PostgreSQL; Ruff and strict mypy pass. Full integrated
checks are recorded separately in the final stack receipt.

Local and external workers claim one existing task lease. External leases begin at
90 seconds and can renew to at most 300 total seconds, capped by credential expiry.
Two external claims may be live at once, leaving independent local role work and the
existing four-job numerical capacity available. An external hourly allowance reserves
at most 600 seconds and 32768 conservative tokens, separately from native inference.
Actual remote tokens/compute/model qualification are unknown. Output and request
allowances are server measured/reserved before delivery and persist across reconnect.
Failed claims consume their reservation; retries do not reset a budget. Renewal
updates the persisted wall reservation. Sixteen current grants and 4096 retained
identities stop new grants rather than deleting old receipts.

A completed response commits before processing. Equal replay reconciles its hash;
different replay cannot overwrite it. Invalid semantic output is retained and cannot
be retried for another verdict. Unknown completion after expiry/release/revocation
requires one explicit local retry and a separate attempt; there is no third attempt.
Revocation preserves completed answers, existing positions and all financial history.
Stale local completion cannot overwrite a subsequently granted/answered stage. The
ordinary proposal ID reconciles lost acknowledgment and funding remains the sole
writer's responsibility. Inference and external waiting hold no financial lock.

## Verification and limitations

`tests/test_research_actors.py` covers local HTTP claim/answer/replay, required
review, actual disposable ordinary paper funding/mature outcome, newly granted
follow-up and disclosed result; cross-scope/spoof/URL/operator failures; expiry and
explicit retry; persisted renewal/budgets; invalid final output; independent local
progress under two external leases; revoked access with actual pending/open paper
positions and history preserved; and a stale local writer. All model answers are
explicit orchestration stubs. Synthetic accelerated maturity is not observed markets.
Hosted selection includes this test file. Full gates and browser integration appear
in issue/draft receipts and the CP23 integrated ledger.

Original failures are retained under ignored `data/cp22-*`: the initial lifecycle
fixture omitted required external evidence capture, its hour-long credential
correctly expired before the mature outcome, and a global proposal count included
legitimate independent deterministic discovery. Fixture corrections provide real
disposable capture, a new explicit grant and an assertion scoped to the one submitted
proposal/trial identity. No archive, expiry, independent discovery or financial
validator was weakened. Private runtime evidence/credentials remain outside Git.
