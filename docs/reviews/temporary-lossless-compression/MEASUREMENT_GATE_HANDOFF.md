# Measurement gate owner diagnosis and handoff

**Keep PR #64 benchmark-only and defer production integration.** One bounded
read-only diagnosis found that the four `model-work` entries were non-model
execution helpers and an idle local workbench API launcher/server pair. The
existing gate matches `training` in their command paths. The resident default
Ollama host showed no loaded models or measurable CPU work in the observed
interval. These facts correct an implication of four active model jobs; they
do not establish an admitted controlled measurement window.

**The remaining blocker is incomplete shared-runtime activity proof.** The
available residency endpoint does not expose pending or in-flight requests,
and all GPU status queries failed to initialize their monitoring interface.
Those failures remain unknown activity, not zero load. Do not repeat the old
gate check or start measuring until an owner-bound activity source or another
reviewed, non-mutating source resolves that gap. No gate code was changed.

This handoff was produced from study head
`7d06558665acbcc157b3caac606d1ebfa64259c2`. Product source remains frozen at
`dcf7ccbb178cdd89175e427962dec80475620c73`; benchmark source remains
`a167fe84e9788fe09cbcf58f716543c169780954`. The prior selection, experiments,
failed receipts and published identities are unchanged. Private process,
listener, source-path, request and job details remain in owned G: receipts.
The adjacent [numeric summary](owner-diagnosis-summary.json) contains only
sanitized aggregate evidence.

An objective validator matched the public summary to the completed private
observation receipts, confirmed all 18 frozen source hashes and the preserved
acquisition/synthetic artifact identities, and passed the private-field screen.
Independent Codex review found no material finding. No new software tests were
run for this documentation-only handoff; the proposed regression cases remain
unimplemented and unrun.

## Observed owners and activity

| Observed role | Evidence | Supported disposition |
| --- | --- | --- |
| Two Codex execution helpers for another local development lane | Bound helper entry points and process trees; matching owner chat idle; zero measured CPU/read/write deltas | Non-model helpers observed idle, not two training jobs. No claim about future activity. |
| Local workbench API launcher and server | Bound command/source/listener identities; three non-mutating job-status projections show zero nonterminal jobs and unchanged durable status totals | Idle heavy-job residency in the observed window. The API process used 0.046875 CPU seconds; no measured process read/write bytes. The launcher is not a second model job. |
| Ollama desktop application's default local host | Bound executable/creation/parent/listener identities; three successful `GET /api/ps` reads report zero loaded models; zero CPU/read delta and 178 process write bytes | No model work confirmed. The write attribution is unknown and may include observation-related logging. Pending/in-flight requests and exclusive consuming-application ownership remain unproven. |
| GPU activity | All three bounded utility checks fail | Unknown; no zero-load or idle-GPU claim. |

The observed process membership and creation identities remained stable at all
three points, with complete process-tree metadata during the window. The
runtime's initial working-directory read was denied; it was not guessed.
Bounded Windows service inspection found no service binding; the desktop parent
is the supported host owner. It was not relabeled as exclusively GIS-owned or
Q-Trades-owned merely from its endpoint.

Ollama documents `/api/ps` as a list of loaded models, rather than an active
request counter. Empty residency therefore supplies part of the diagnosis,
not complete request-quiescence proof. See the
[official endpoint contract](https://docs.ollama.com/api/ps).

## Declared diagnosis protocol and limits

The protocol was declared before observation: three points at offsets **0, 15
and 30 seconds**, with the same identified owners and their descendants. Each
point binds creation/executable/parent identity, CPU, process I/O, memory,
threads and process membership; it also reads workbench job status, model
residency and available GPU counters. The operation completed in 30.641 seconds,
or 31.344 seconds including supervision.

Each status request had a two-second timeout and 64-KiB response limit. Process
trees were capped at 64 entries and job metadata at 4,096 rows. A single IDLE
diagnostic child ran with the existing hard 512-MiB ceiling and 60-second
operation deadline. Total owned study scratch was 264,950,624 logical bytes,
including required earlier receipts, below the unchanged 1-GiB ceiling. All
temporary output remained on verified private G: scratch.

The local workbench's existing job-reading services reconcile durable records.
They were not invoked. Its status-only metadata projection used pinned SQLite
3.49.1 `mode=ro&readonly_shm=1`, query-only reads, normal locking/change
detection and bounded progress; it constructed no owner service and made no
database changes. This does not claim global DB/WAL/SHM bytes were unchanged
under other writers. No raw examples, targets, model files or manifests were
opened. The failed initial service-query interpretation, successful fallback
and failed GPU observations are retained privately.

These are uncontrolled diagnostic observations, not codec, restore, access,
tail-latency or device-I/O measurements. Zero model requests and zero benchmark
samples were dispatched. No process was stopped, reconfigured, unloaded or
interrupted. A short observation establishes its recorded scope and provides
no continuous or future quiet-window guarantee.

## Smallest proposed benchmark correction

Confine a later correction to the existing `scripts/compression_study/resources.py`
classifier and its cases in `tests/test_compression_study.py`. The correction is
**proposed, not implemented**; its regression cases below have not been run.

1. Classify an invocation from its executable and explicit script/module/operation
   arguments. Directory names and `--working-dir` values do not establish a
   training operation. Preserve actual training, inference, qualification,
   benchmark, build and test invocation detection.
2. Separate the identified role from activity evidence. Known execution helpers
   and API `serve` invocations are not automatically active model work. They
   qualify as observed idle only with current owner/request proof, complete
   identity/membership checks and compatible resource observations. Otherwise
   report unknown activity; do not silently discard opaque commands or children.
3. Preserve refusal for active work and unknown activity. Empty `/api/ps`, zero
   sampled CPU, a resident-process name, a stale receipt or a failed GPU query
   cannot individually establish idle. The shared host therefore remains refused
   on this evidence even after correcting the four misleading classifications.

Use the same declared three-point preflight for a later reviewed correction.
Before each preparation/access operation and during the existing supervisor's
before/during/after checks, require fresh owner/request state, stable process
identities and no unexplained work or observation failure. Record polling and
startup overhead separately and include full supervisor costs consistently
across every arm. If work starts, a listener changes, a process disappears or
reuses an identity, or status becomes unavailable, refuse the measurement and
retain the incomplete receipt. This adds no production observer, service,
process exemption, manual quiet flag or new benchmark framework.

### Required regression cases

| Case | Required result |
| --- | --- |
| `training` appears only in a working-directory/project path for a bound execution helper | No active-model classification from that word; incomplete activity proof still refuses. |
| A bound API launcher/server pair uses `serve`, has zero nonterminal jobs and compatible resource observations | Service residency is distinct from model execution; identities and child coverage remain required. |
| A real training/qualification/inference worker, queued or starting model job, or opaque execution command is present | Active or unknown activity refuses; a quiet server parent does not hide a worker. |
| Parent/redirector and child represent one API owner | Correct role accounting; every relevant process retains separate identity/resource evidence. |
| `/api/ps` is empty or models are merely resident, but request state is missing | Unknown request activity refuses. |
| Owner status says idle but CPU/I/O changes are unexplained, GPU monitoring fails, or a short job changes durable counters | Do not accept sampled idle as a controlled window. |
| Request read times out, access is denied, state is stale, source/listener identity changes, a new child appears, or a PID is reused | Refuse and retain the precise failure. |
| Work begins while the existing supervisor is measuring | Preserve the existing overlap refusal and incomplete samples; no uncontrolled-to-controlled relabeling. |
| Public diagnostic export | No PIDs, usernames, command lines, model names, private roots, request IDs, payloads or manifests. |

## Specific resumption condition and evidence boundaries

The next useful action is an owner-bound, non-mutating indication of current
pending/in-flight work and usable resource observations for the shared host,
followed by review of the narrow classifier proposal. If such status is not
available, keep it unknown and defer; do not launch another unchanged waiting
cycle or interrupt the owner to make the machine appear idle.

Measurement prerequisites are safe frozen input, an admitted observation window,
exactness checks, comparable durability/verification semantics, the pinned
three-arm/five-repetition randomized protocol and existing resource reserves.
The production read-latency decision and capture-owner repair/disposition belong
to later integration acceptance; they are not automatic prerequisites for
collecting valid benchmark observations. This diagnosis does not explain or
take ownership of the recorded capture failures, whose deadlines/assertions
remain unchanged.

The eight-candidate draw, seven protected exclusions and the one eligible
860,160-byte frozen specimen are preserved. No replacement draw was made.
Completing representative coverage requires an explicit new sampling plan
reconciled with the original eight-specimen/128-MiB/32-MiB limits, not an
undocumented redraw. Measuring the existing sparse file could supply a scoped
result once admitted, but would not establish representative savings.

PR #64 remains draft and benchmark-only. Production integration is deferred.
No operating compression, replacement, deletion, activation or space reclamation
was performed. Keep the existing capture owner, operating protections, private
Lab, GIS, paper trader and parallel lanes intact.
