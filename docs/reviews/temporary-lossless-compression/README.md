# Temporary-segment lossless compression study

Across three small synthetic SQLite segments, Zstandard level 1 reduced identical
container bytes from **245,760 to 58,581 bytes (76.16%)**, with exact length/SHA-256
restoration and complete record, availability and reference preservation. Gzip
level 9 saved 74.34%; the fixed LZ4 profile saved 64.89%. The prototype's Zstandard
payload plus manifest/claim lengths total 59,973 bytes; reported data-stream
allocation totals 62,856 bytes. These are fixture replacement calculations.

All 35 final fixture operations completed, with one observation per arm. That
fixture result contains **zero real specimens**. Both performance attempts were
deferred because a quiet window could not be established. Real-drive benefit and
an acceptable production read/CPU/I/O tradeoff remain **inconclusive**. The first
candidate for a later representative experiment is Zstandard level 1; this result
does not support enabling temporary compression yet.

See [RESULTS.md](RESULTS.md) for all byte, allocation, timing, staging and memory
tables, [synthetic-results.json](synthetic-results.json) for exact individual
samples/profiles/source identities, and [VERIFICATION.md](VERIFICATION.md) for the
retained attempts, commands and unresolved existing-test failure.

This is a benchmark lane. It changes no operating storage reader, writer,
recovery state machine, quota, retention, reserve, protection or setting. The
400 decimal GB temporary / 100 decimal GB retained policy remains the operating
contract. Originals are untouched, so a codec ratio is not reclaimed space.

The approved continuation adds frozen-input admission, direct/copy/Zstandard-1
access controls and bounded owner diagnostics. It reuses the published synthetic
SQLite files for software validation. Representative real acquisition and
controlled performance remain separate prerequisites; details and the retained
continuation attempts are below and in [VERIFICATION.md](VERIFICATION.md).

## Real acquisition follow-up

The approved G: verification established **one independently reviewed real frozen
SQLite copy: 860,160 bytes and one decision record**. Original and frozen length
and SHA-256 match exactly. The private copy passes integrity, schema, complete
record/availability/timestamp and exact-reference checks through the existing
importer. No real compression, restoration or controlled access sample ran.
See [real-acquisition-summary.json](real-acquisition-summary.json) for sanitized
selection, correctness, allocation and acquisition-resource evidence.

Before examining any compression outcome, the bounded frame covered the earliest
and latest 512 indexed segments, with intervening segments unobserved. A seeded
age/size draw selected eight candidates totaling 89,935,872 logical bytes. Their
content was classified before compression; the draw was not content-balanced.
Seven candidates were excluded because embedded market-information history
overlapped protected evaluation windows. Rejected candidates were not replaced.
The remaining recent, sub-1-MiB decision has no frames, bars, study, numerical
rows, observed trades or feature origin. Older, fuller, wire and mixed-content
real strata remain missing. This is specific acquisition evidence, not a
representative savings sample or an operating eligible-byte denominator.

The closed-container route binds the root/plan/volume, exact owner marker,
completed indexed lifecycle, full record tuple, current protections and source
identities. Source/pin/expiry/reclamation facts were refreshed around a byte copy
using short read-only handles shared for writes and deletion. No operating
constructor, recovery, checkpoint, VACUUM, pin or owner lock was used. The
independent review repaired incomplete clock/shape checks before acquisition.
Known prepared-handoff windows were checked through metadata only; two legacy
Lab manifests lack source mappings, and one of seven prepared manifests lacks
review metadata. These limits do not establish comprehensive historical Lab
source independence. Real payloads, paths, IDs, hashes and receipts remain private.

The fresh five-repetition gate deferred with four foreign test processes, four
model-work classifications and one unclassified resident runtime. It dispatched
**zero preparation or measurement children**; see
[real-access-measure-deferred.json](real-access-measure-deferred.json). Its null
real-specimen count means the gate returned before loading the separately
validated private packet. No other owner was stopped. Representative savings,
full access/resource costs and an approved product latency tradeoff remain
unmeasured; the recommendation continues to **defer production integration**.

## Source, ownership and sampling boundary

Main was refreshed once from the prompt's `fca588586f9b72e9506caef6384ee8e65edea738`
to `dcf7ccbb178cdd89175e427962dec80475620c73`. The separate branch is
`codex/temporary-lossless-compression-study`; all source measurements use this
frozen product base plus the benchmark-file identities recorded in the result.
Root instructions, current research status, storage/recovery code, #54's capture
recovery report, worktrees, dirty files, locks and active processes were inspected.
No active Git lock/merge/rebase was observed at the initial inspection.

At that inspection, #61 (knowledge/reviewer work) had merged as `dcf7ccbb`.
#63 remained an independently owned draft for financial monitoring/shutdown.
Drafts #57 and #62 retained their own receipts. Unrelated import-checkout files,
an original audit test tree, and monitoring-worker/API test edits were preserved.
No installation is inferred from GitHub state. At that initial inspection, only
the existing operating
storage-plan and cached status JSON were inspected; no operating SQLite database
was opened, backed up, hashed, repaired or instantiated through `ResearchStorage`.

The cached receipt at initial inspection reported approximately 127.2 decimal GB
temporary and 18.0 decimal GB retained-tier usage, with pending and protected
segments. These are sanitized cached logical accounting totals, not a fresh
inventory, eligible-byte denominator or physical allocation measurement.
Their file-type/age distribution and currently eligible fraction are unknown.
Its last maintenance reported zero reclaimed bytes. Detailed operating metadata
stays private. No whole-archive scan was performed.

No authorized, consistent, frozen real specimens were established in the initial
publication. The reviewed follow-up above adds one specific private copy. Operating
active segments, journals, protections, evaluation material and other projects
were left alone. Repeated observations found foreign test activity and an
unclassified resident model runtime. The quiet-window gate therefore defers
performance work instead of stopping another owner or weakening a guard.

## What the storage owner currently does

The inspected owner is `src/trading/research_storage.py`:

- `_bytes` sums logical file lengths of all immediate files in the owned tier,
  including indexes, WAL/SHM, scratch and unexpected files. It does not count
  NTFS allocation. `snapshot` also charges the root ownership marker to retained
  usage. Segment `bytes` is payload accounting and is not a file-size denominator.
- `admission` checks the declared volume identity, free-space reserve, scratch
  reserve and tier quota. No reserve or quota was altered by this study.
- `_append` writes bounded, ordinary rollback-journal SQLite segments, including
  `records(id,sha,body)` and `record_availability(id,available)`. The index owns
  references, states, pins and expiry. Active input must remain writable and
  recoverable through that owner.
- `_housekeeping` moves active segments to sealed state and transfers at most
  two sealed segments into verified JSONL gzip archives per pass. The actual
  gzip setting is Python's default level 9. A retained row can still have its
  original temporary SQLite file: expiry, pin/protection and verified destination
  checks precede the existing owner's eventual removal. That overlap is legitimate.
- `reopen` first uses an existing SQLite segment and its exact ID/hash. Once
  absent, it verifies the retained compressed file hash, scans gzip JSONL and
  checks the requested payload hash. It never substitutes a nearby reference.
- Startup can acquire ownership and reconcile a hot rollback journal. #54's
  verified owner may open eligible owned segments non-creating in write mode;
  ordinary historical readers remain read-only. Constructor startup is not an
  inventory API. No such constructor was used on operating data here.

Pinned, retained, expiry-waiting and active are lifecycle distinctions, not
permission to compress or remove a file. A sealed label alone proves neither
snapshot consistency nor absence of another writer.

## Fixture and codec protocol

### Approved continuation protocol, declared before new observations

Continue the same draft PR #64, branch and worktree. The resumed starting study
head is `14029309ea0439b643b51eb8c0217d174184e149`; the product base remains
`dcf7ccbb178cdd89175e427962dec80475620c73`. Record benchmark module/test hashes
for each experiment and do not rebase while measuring. The historical
`synthetic-results.json` is preserved byte-for-byte. Its outcomes are already
known; reuse of those three SQLite files is software verification, not new
representative sampling.

Predeclare marginal coverage across age, content and size, with seed 20261005:

- Age uses authoritative completion time relative to one recorded UTC selection
  time: under 1 day; 1 through 7 days inclusive; over 7 days. Filesystem mtime
  is not completion evidence.
- Content: wire; decision-summary; mixed-other. Classify from reviewed owner
  evidence before compression, not from the resulting ratio.
- SQLite file size: below 1 MiB; at least 1 MiB and below 8 MiB; at least 8 MiB
  through 32 MiB. Prefer fuller completed segments when safely available.

Eight specimens cannot cover all 27 joint cells. Record candidate-frame size,
eligibility/exclusion counts, missing marginal/joint strata and any cap-induced
omission privately before selection. Use at most eight real specimens, at most
32 MiB per file and 128 MiB combined input. No eligible operating-byte denominator
is currently known. Selected-input totals count each original once, independent
of repetitions and read workloads. JSONL codec comparisons retain their separate
historical denominator; the continuation access controls are SQLite only.

Prefer already authorized frozen copies. The bounded private-scratch inspection
found accessible synthetic generation receipts and their original files, but no
reviewed eligible real acquisition. Inaccessible historical test directories
were not searched exhaustively. Cached operating totals do not establish a
per-segment candidate frame, consistency, ownership, pins, pending outcomes or
evaluation protections. No operating database was opened in that first
continuation inspection; the follow-up above adds bounded reviewed read-only
metadata/eligibility checks without an operating constructor.

The real handoff must provide an already-frozen private SQLite file, exact
length/SHA-256, and the digest/length of an independently reviewed acquisition
receipt. That receipt binds prior authorization, custody, owning plan/segment,
completion and acquisition times, eligibility as of the declared selection time,
consistency method and journal disposition, transformations, exclusions and the
independent review. The importer checks receipt/file identities, bounds, paths,
single-link ownership, sidecar absence, schema, complete evidence and probes.
It validates a reviewed handoff format; a populated JSON receipt cannot itself
prove truthful original acquisition. The follow-up verified a closed-container
byte-copy route for one specific completed source, with separate independent
acquisition review.
A sealed label alone is insufficient, and no mutable input uses `immutable=1`.

Compare three controls with identical reference selections and full evidence
validation: direct original frozen SQLite; uncompressed copy/flush/hash/read;
Zstandard-1 restore/flush/hash/read. Test one middle exact reference and a bounded
same-segment batch of first/middle/last/seeded-random references plus a small
range. Prepare each encoded artifact once; run each read in a fresh supervised
child, sharing a single restore within that batch. Add no cache or representation.
All arms hash the original source and separately validate the complete SQLite
evidence. Report those costs as well as access, stream I/O, codec, durable flush,
hashes, SQLite reads, module-import startup, worker and supervisor elapsed/CPU.
Supervisor elapsed includes launch/scheduling; import time alone is not startup.
Process I/O counters include imports and are not measured device traffic.

Acceptance is declared before new results:

- Exact original/restored length and SHA-256, integrity, schema, IDs/hashes,
  raw payloads, availability and timestamps must match. One-reference and batch
  results must agree across all arms. Retain all existing failure/recovery cases.
- Any resource refusal, source drift, failed verification or overlap invalidates
  completion. Enforce one IDLE codec child, fixed single-thread profiles, hard
  512 MiB child memory, 1 GiB total owned scratch, 60-second operation and
  900-second measured phase limits, plus the stricter operating free reserve.
  Child `TEMP`/`TMP` are individually owned G: directories under private receipts.
- Controlled runs require a quiet window before, during and after child work,
  five repetitions in seeded randomized blocks, and individual samples with
  median/min/max. A bounded recheck may establish deferral; do not stop another
  owner or poll indefinitely. Smoke observations have no reliable tail, cold-cache
  or representative-performance interpretation.
- Report payload and metadata/claim replacement lengths, supported stream
  allocation, full restored scratch and legitimate original/retained overlap.
  Unknown allocation remains unknown. No predetermined savings percentage is
  required; expansion and no-benefit outcomes remain valid evidence.
- No product-level read-latency/CPU/I/O acceptance threshold is approved. Positive
  selected-file savings alone cannot justify integration. A recommendation may
  defer with the exact acquisition, latency decision or owner-recovery gap.

Bounded capture diagnostics run the unchanged recorded failing test once without
tracing, then at most twice with owner/lock/recorder call tracing if useful. Keep
its original five-second deadline and assertions. Record import/launch cost,
lock releases and recorder transitions in private disposable state; tracing adds
overhead. Current passes and hosted checks do not diagnose historical failures.
Changes needing the production owner are handed off, not patched in this lane.

Three small finalized SQLite fixtures use the actual existing writer, with
24 records each: repeated structure, varied seeded hexadecimal content, and
less compressible seeded base64 content. Each preserves Unicode (including a
combining character), an exact long decimal string, a timestamp with offset,
null versus missing fields, arrays and original availability. A separate 64-KiB
seeded random byte fixture tests deliberate incompressibility. This fourth
fixture has no evidence-record schema and is labeled raw throughout.

After each destination writer closes, the study freezes exact bytes/SHA-256,
schema, every ID/hash/raw body, every availability row, record count and probe
references. No SQLite checkpoint, vacuum, page removal or body normalization is
part of container compression. Complete SQLite integrity and evidence signatures
are checked. The original writer's `reopen` also checks every generated reference.

Two comparisons have independent denominators:

1. **SQLite container:** every arm receives the same finalized file, including
   tables, indexes, allocation inside SQLite pages and unused page content.
   Every restored file must have the original length/hash and complete schema,
   raw record and availability signatures.
2. **Existing archive representation:** the same ordered canonical objects used
   by `_housekeeping`, containing ID, hash, payload and availability, are emitted
   as UTF-8 JSONL with the host's native text newlines. On this Windows host that
   includes CRLF. Every arm receives identical frozen JSONL bytes. A separate
   complete evidence signature proves export equivalence; layout savings are
   never assigned to a codec. An actual disposable owner archive is checked
   byte-for-byte against the study's export in the focused tests.

Profiles are uncompressed copy, gzip level 9, Zstandard levels 1 and 3 with
`threads=0` (synchronous single-thread operation), and LZ4 frame level 0 with
linked 64-KiB blocks, explicit size, content/block checksums and no auto-flush.
No dictionaries or extreme settings are used. Gzip uses the application's
compression level and a fixed synthetic filename/mtime so its header is
reproducible; this is not byte identity with an existing retained gzip file.
Exact Python/package/native-library versions and profiles are in the results.

The planned measurement protocol uses seed 20261005, randomized arm/specimen
order within each of five repetitions, with individual samples, median and
range. It has no tail-percentile claims. The small correctness smoke is separately
labeled and has one repetition. First-observed study reads occur after fixture
generation, hashing and verification; they are not controlled cold-cache reads.
Later observations are warm repeats. Caches are never cleared.

## Read, resource and space accounting

For SQLite the direct reader opens the original and reads the same first,
middle, last, seeded random and small-range records. The compressed path first
hashes/validates its artifact and manifest, restores the entire segment to
bounded scratch, verifies the exact restored length/hash, then opens SQLite
and reads that selection. One requested record therefore requires full-segment
restoration. Integrity/complete equivalence are checked at publication, separately
from this read timing. Exact restored bytes preserve that verified integrity.

For JSONL, reopening includes artifact hash validation, full bounded restoration,
complete evidence verification and a full scan for the same selection/range.
This is stronger than the existing owner's early-exit archive reader and uses
two JSONL passes; it is not a claimed faster production-equivalent shortcut.
Comparisons against uncompressed JSONL use the same verification/scan work.

Individual samples retain elapsed/process CPU time for compression, decoding,
codec work, input/output I/O, durable flush, verification, metadata write and
rename. Worker startup and whole-supervisor elapsed are separate. Tiny process
CPU samples may be zero at the OS accounting granularity; that does not establish
zero CPU work. Phase sums can differ from total time because Python/control and
open/close overhead are not codec time.

Physical data-stream allocation uses Windows
[`FILE_STANDARD_INFO.AllocationSize`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info).
Normal NTFS streams are measured independently of logical length. Sparse,
filesystem-compressed and redirected streams return unknown here. MFT, directory
and volume metadata are excluded, so these numbers are not total volume allocation.
`GetCompressedFileSizeW` is not used for ordinary-file allocation: its uncompressed
case can report the same value as logical size, as the
[Microsoft documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew)
states. The initial smallest smoke's old allocation fields are invalid for this
purpose and are not used in the final physical-space conclusion.

Each arm separately charges compressed payload, manifest and claim-file lengths.
Actual allocation for those streams is also recorded. Maximum staging includes
compressed partial + full restored verification copy + manifest; the original
specimen remains present separately. A future safe transition needs the original,
compressed result, decoder/verification scratch and durable metadata/index
headroom at the same time. Existing temporary/retained overlap remains additional.
A smaller JSONL codec result affects the retained representation only; it does
not automatically change temporary usage. Both operating quota changes and
actual reclaimed bytes are exactly zero for this lane.

All experiment artifacts and pinned dependencies use newly owned private G:
scratch outside Git and the operating managed subtree, with a verified NTFS
identity, private user/System ACL, ownership token and free-space reserve.
There is no C: spill. The CLI checks its ownership marker, excluded live root,
volume, free-space floor and 1-GiB conservative total file-length charge, including
its environment/cache. One codec child runs at a time at Windows IDLE priority.
It requires the exact release byte before importing the benchmark, refusing EOF
or a wrong token, so the existing `ChildOwner` utility can
enforce a 512-MiB process-commit limit and kill-on-parent-close job first. Peak
working set and committed memory are observed per child, including imports and
verification; this is not a codec-only peak. Non-Windows job enforcement is
explicitly reported as unavailable. Per-child deadlines are 60 seconds and the
measurement phase is at most 900 seconds. No service or foreign process is stopped.

## Correctness and interruption boundary

The local prototype writes a unique partial directory, completes and flushes the
codec payload, restores/verifies it, verifies evidence, writes/fsyncs its manifest
and atomically renames the directory to its published result name. It uses the
existing OS-released lock for concurrent claims. A partial-directory manifest
cannot be consumed as a published result. There is no overwrite of a prior result.

Tests cover exact repeated/random round trips, actual owner archive equivalence,
truncation, corruption, trailing frames, wrong codec/version, invalid declared
sizes, bounded expansion, stale manifests/sources, checksum-disabled frames with
wrong expected hashes, simulated ENOSPC, actual process exits around publication,
cross-process claims, actual Windows destination sharing locks, finite deadlines,
unresolved sidecar refusal, allocation accounting and private-data publication
refusal, a one-record reference/range, and actual bootstrap EOF/wrong-token refusal.
No operating disk is exhausted, no operating file is corrupted, and no
recovery sidecar is deleted. Only precisely named disposable decoder outputs are
removed; failed attempts and private receipts remain.

This proves a prototype boundary. It does not prove deployed reader compatibility,
power-loss directory durability, storage-index migration or installed acceptance.

## Verification ledger

The expanded focused module passed **67 cases**, with zero skips, without a
caller-supplied import path. After the final narrow readiness-marker correction,
all **seven affected process interruption, claim and release-token cases** passed
again. Scoped Ruff passed; Windows-targeted strict mypy passed for seven study
source files. Independent Codex source review found two material issues and a
readiness race on recheck; all were repaired and confirmed resolved by the reviewer.

The broader disposable storage selection is **not green**: 17 existing cases
passed, while the unchanged
`test_normal_recorder_retries_busy_startup_recovers_and_records_without_manual_repair`
missed its five-second recording deadline on two attempts. Its root cause is
unproven and is handed to the existing capture/storage owner. A focused rerun
does not supersede that failure. No product test or deadline was weakened.

Early harness failures, the discarded allocation pilot, the failed readiness
marker read and all later passes are retained in [VERIFICATION.md](VERIFICATION.md).
The final small comparison uses the frozen post-review source, restores all 35
inputs exactly and records all profiles, identities and individual observations.
Five repetitions and real-data performance remain deferred rather than passed.

Exact private attempt commands/outputs stay in the study receipt directory.
Public code, generated fixture definitions and sanitized numeric results alone
are committed. The focused test module skips individual optional-codec cases when
the dedicated dependencies are absent; hosted product requirements are unchanged.
These skips are not benchmark proof.

The existing PR workflow matches `scripts/**` and `tests/**` and can run its
normal product gates. Its triggers and existing failed-run steps were inspected;
no hosted-usage hold was found in the checked instructions/run evidence. No workflow
was disabled, edited or manually dispatched; no benchmark matrix, full local
product suite, dashboard rebuild or shared database service was started for this
lane. Hosted status remains a separate proof stage from this local fixture study.

## Smallest later handoff and decision

Prioritize **Zstandard level 1** for a later bounded real-sample/quiet-window
experiment. It gives the smallest combined SQLite fixture output; level 3 improves
only the repeated container by 53 bytes. All compressed arms enlarge the raw
random fixture. On identical JSONL exports, Zstandard level 1 gives only 5.38%
additional payload savings over the already-compressed gzip representation.

Whole-segment restore/fsync adds a material observed read cost: compressed SQLite
fixture reopen intervals span about 121–333 ms, versus about 1.8–3.4 ms for direct
selected-record reads. These timings overlap other workload and are not a
production latency threshold or a reliable codec-speed ranking. Peak working set
was 34.87 MiB and commit 23.90 MiB; total observed process threads were four in
every arm, including the uncompressed control, distinct from configured codec
threading. Conservative owned-scratch charge was 215.49 MiB, including the
environment/cache and retained attempts. No disk-device throughput, UI latency or
whole-machine coexistence acceptance was measured.

The uncompressed restore control was also expensive. Its historical intervals
were about 132–146 ms. The mixed Zstandard-1 example spent about 0.269 ms in codec
work and 110.383 ms in durable flush within a 121.363-ms restore/read interval.
Copying, artifact/source hashing, flush, verification and reads must be attributed
separately. These uncontrolled observations do not assign all restore cost to
decompression or establish a reliable codec ranking.

**Defer production integration.** The eligible real-byte denominator, controlled
read/CPU/I/O acceptability, recovery/index integration and installed acceptance
must be established first. No estimate is applied to the entire temporary tier.

The implementation owner would remain **`ResearchStorage`**, including its existing
storage index, admission, segment recovery, housekeeping and exact-reference
reader. The smallest candidate is a versioned representation for **completed,
unprotected temporary SQLite segments**, leaving active SQLite and existing
retained gzip unchanged. Add codec/version, original/encoded length/hash and
publication state to that owner's authoritative segment metadata; reuse its
exclusive owner and safe staging boundary. Restore a complete verified SQLite
copy into admitted bounded scratch for exact lookup. Do not introduce another
storage owner or write these changes from this lane.

Before production work, use an authorized quiet window and non-cherry-picked
frozen real samples. Declare age strata (under 1 day, 1 through 7 days and over
7 days), content kind and
file-size strata before selecting, with seeded choice within eligible strata,
at most eight samples and 128 MiB total uncompressed input. Exclude active,
unresolved, unknown-owner, pinned/pending-outcome and evaluation material. Prefer
existing authorized frozen copies. A live read-only backup is only acceptable
after proving it won't initiate recovery/sidecar writes or hold a long transaction;
otherwise skip it. Record backup/layout transformations separately from compression.
Do not feed a mutable database to `immutable=1`.

Required integration evidence remains: legacy SQLite and gzip reads; exact IDs,
hashes, raw bodies and availability; active/retained/pinned/expiry-waiting behavior;
index/manifest mismatch; interrupted publish/index acknowledgment and crash before
and after original removal; retry and restart ownership; hot-journal recovery;
concurrent readers/writers; quota/free-space/scratch accounting through overlap;
decoder memory/expansion limits; resource-guard yielding; bounded record-read
latency and CPU/I/O under approved coexistence; rollback preserving originals;
native/browser installed acceptance under separately authorized rollout. Any
extrapolation must use measured eligible strata and their known coverage, not
the entire 400-GB tier.

## Reproduce

Use an independently created private G: QA directory with a restricted ACL,
outside every checkout and the live managed subtree. Verify the volume's identity
and actual operating free-space reserve first. Generate a fresh ownership token
and `study-owned.json` containing `lane`, `owner_token`, `volume_identity`,
`max_scratch_bytes=1073741824`, and `min_free_bytes` no lower than the operating
reserve (the initial observed reserve was 5368709120). The CLI intentionally
requires this marker and explicit live-root exclusion; it does not create
ownership of an arbitrary directory. Never reuse another owner's scratch or a
previous pytest `--basetemp` directory.

From the frozen study checkout, with the placeholders referring only to your
new private scratch/environment:

```powershell
# Create only a dedicated environment. Direct pip/cache/temp to owned G: scratch.
$env:TEMP = Join-Path $StudyScratch 'temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $StudyScratch 'pip-cache'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = Join-Path $StudyCheckout 'src'
& $BasePython -B -m venv (Join-Path $StudyScratch 'environment')
$StudyPython = Join-Path $StudyScratch 'environment/Scripts/python.exe'
& $StudyPython -B -m pip install --no-input --only-binary=:all: `
  -r scripts/compression_study/requirements.txt

& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 `
  --mode smoke --smallest --repetitions 1 --seconds 120

# Gate-controlled five repetitions; exit 3 means deferred before measurement.
& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 `
  --mode measure --repetitions 5 --seconds 900

& $StudyPython -B -c "import psutil,pytest,sys; psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS); raise SystemExit(pytest.main(sys.argv[1:]))" `
  -q -p no:cacheprovider --tb=short --basetemp $NewPrivateTestDirectory `
  tests/test_compression_study.py
& $StudyPython -B -m ruff check --no-cache scripts/compression_study tests/test_compression_study.py
& $StudyPython -B -m mypy --platform win32 --follow-imports=silent `
  --ignore-missing-imports --cache-dir $PrivateTypeCache scripts/compression_study

# Historical synthetic exporter; preserve the original published result.
& $StudyPython -B -m scripts.compression_study.sanitize `
  --private-result $PrivateResult --output $NewPublicSyntheticResult
```

The CLI generates synthetic fixtures unless `--frozen-specimens` supplies a
reviewed private handoff. That importer admits only inputs inside verified private
scratch; the synthetic branch requires the published generation identity and
the real branch requires independently reviewed acquisition/eligibility evidence.
It does not acquire operating data. Exit 2 denotes a failed run with retained
private receipts; exit 3 denotes a deferred measured run.
The smallest smoke is a correctness starter, not real-drive evidence. See
`RESULTS.md` and `synthetic-results.json` for the recorded study result and exact
individual samples.

For the continuation, reuse an eligible reviewed handoff packet and the existing
owned environment. No new environment or framework is required:

```powershell
& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 `
  --frozen-specimens $PrivateFrozenPacket --mode measure --repetitions 5 --seconds 900

# One repetition is separately labeled software validation.
& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 `
  --frozen-specimens $PrivateFrozenPacket --mode smoke --repetitions 1 --seconds 300

# Numeric allowlist; review the aggregate before committing it.
& $StudyPython -B -m scripts.compression_study.sanitize `
  --private-result $PrivateAccessResult --output $NewPublicAccessResult --access-aggregate

& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 --diagnose-capture plain
# If useful, repeat once or twice with --diagnose-capture trace in fresh private state.
```

**Benchmark-only. No operating compression, replacement, deletion or activation
was performed. Zero operating bytes were reclaimed. Initial metadata-reader SHM
bookkeeping was not measured; see [VERIFICATION.md](VERIFICATION.md).**
