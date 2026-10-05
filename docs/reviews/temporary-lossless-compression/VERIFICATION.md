# Verification and retained attempts

Product source is frozen at `dcf7ccbb178cdd89175e427962dec80475620c73`.
The final synthetic result records SHA-256 identities for every benchmark module,
this test module, the relevant existing owners, the shared lockfile and project
configuration. Documentation is outside that source hash set. The dedicated
environment uses the pinned study requirements; no product dependency changed.

All test state, process markers, specimens, caches and unsuccessful receipts are
private disposable study artifacts. No operating database or service was used.
The commands below use variable placeholders to keep private locations out of Git.
Each attempt used a newly named test directory; no earlier `--basetemp` was reused.

## Observed local ledger

| Attempt | Observed result | What the result establishes |
| --- | --- | --- |
| Initial smallest smoke | 10 operations completed | Two-record round trips on repeated SQLite/JSONL. Its original ordinary-file allocation fields were wrong and are excluded from physical-space findings. |
| Focused attempt 1 | 51 passed, 5 failed, 76.02 s | Three disposable archive tests used a maintenance time before the due threshold; two expansion tests exposed incorrect assumptions about Zstandard window-argument units. Both harness causes were corrected. |
| First scoped static checks | Ruff: 38 findings; types: 10 findings | All were repaired in owned benchmark paths; original outputs were retained. |
| Focused + existing storage attempt 2 | 73 passed, 1 failed, 236.21 s | 56 then-current study cases and 17 existing cases passed. One unchanged existing capture test missed its five-second startup deadline. |
| Focused + existing-test retry attempt 3 | 63 passed, 1 failed, 94.02 s | Expanded study cases passed; the same unchanged existing test failed again. This did not make the broader selection green. |
| Study-only attempt 4 | 63 passed, 86.27 s | Added timing/metadata instrumentation verified locally. |
| Reviewed study-only attempt 5 | 64 passed, 77.48 s | Includes the one-record probe/range correction. |
| First full fixture comparison | 35 operations completed | All declared fixture representations/arms round-tripped. Superseded for final source identities and timing by the post-review run. |
| Reviewed-source fixture comparison | 35 operations completed | Repeat after the one-record correction; retained as pre-independent-review evidence. |
| Independent review | Two material findings, then a readiness race on recheck | Refused EOF/wrong release token before worker import, made crash/claim child imports independent of caller environment, and published a closed readiness marker through rename. Read-only review; no private data, tests or services inspected by the reviewer. |
| Review-fixed focused attempt 6 | 67 passed, 90.15 s, zero skips | Ran with empty caller `PYTHONPATH`. A narrow readiness-marker patch occurred during this run; it is not the final verification of that patch. |
| Review-fixed lint attempt | One line-length finding | Formatting was corrected; failed output was retained. |
| Affected attempt 7 | 6 passed, 1 failed, 7.84 s | The parent's unnecessary readiness-marker content open returned `PermissionError`. A later inspection found the intact marker readable; the OS cause is unproven. The handshake now uses the completed rename acknowledgment and live child, with the actual lock-contention assertion as its proof. |
| Final affected attempt 8 | 7 passed, 9.84 s, zero skips | Actual exit-before/after-publication, cross-process claim/release, and bootstrap EOF/wrong/right release cases passed without caller `PYTHONPATH`. |
| Final scoped lint | Passed | Owned study modules and focused test module only. |
| Final scoped Windows types | Passed, 7 source files | Owned study modules only; dependencies/imported product code were not a new full-product type run. |
| Five-repetition gates | Deferred, exit 3 on both attempts | Foreign test/qualification activity and an unclassified resident model runtime prevented a quiet-window claim. No controlled five-repetition measurement dispatched. |
| Report generation check | An assumed one-process-thread invariant was rejected | The recorded observations show four total process threads in every arm, including the uncompressed control. The final report distinguishes that count from the codec's explicit single-thread setting; no thread-level CPU attribution is claimed. |
| Final post-review fixture comparison | See [RESULTS.md](RESULTS.md) and [synthetic-results.json](synthetic-results.json) | Frozen reviewed source, one repetition per arm, small synthetic data only. Timings are uncontrolled smoke observations. |

The unresolved existing failure is
`tests/test_capture_recovery.py::test_normal_recorder_retries_busy_startup_recovers_and_records_without_manual_repair`
at its five-second wait for the recorder to reach `recording` after peer release.
It reproduced twice against the unchanged existing implementation/test. Neither
the deadline nor product recovery code was modified. The root cause is not proven;
overlapping workload alone is not a diagnosis. This is a handoff to the existing
capture/storage owner, not a green storage acceptance claim.

The original broader selection contains all 13 tests in
`tests/test_capture_recovery.py` and these five existing cases:

- `tests/test_research_storage.py::test_rollovers_reopen_pending_and_two_hour_continuation`
- `tests/test_research_storage.py::test_failed_transfer_last_source_checksum_and_recovery`
- `tests/test_research_storage.py::test_legacy_frozen_backup_versioned_limits_and_single_maintenance`
- `tests/test_research_storage.py::test_interrupted_segment_ack_recovery_and_consistent_rollups`
- `tests/test_research_storage.py::test_absence_mapping_access_and_quota_no_spill`

## Exact argument templates

Use the frozen study checkout as the working directory. Set `TEMP` and `TMP` to
the new private study temp directory and disable bytecode. The normal CLI needs
the checkout's `src` path. The last focused/affected tests deliberately set the
caller's `PYTHONPATH` to the empty string and rely on pytest's declared parent
path plus the test's explicit scoped child environment.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = Join-Path $StudyScratch 'temp'
$env:TMP = $env:TEMP
$env:PYTHONPATH = ''

# The runner sets Windows IDLE before pytest; arguments pass through unchanged.
& $StudyPython -B -c "import psutil,pytest,sys; psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS); raise SystemExit(pytest.main(sys.argv[1:]))" `
  -q -p no:cacheprovider --tb=short --basetemp $NewPrivateTestDirectory `
  tests/test_compression_study.py

# Original broader selection: add these arguments to that same pytest runner.
# All paths refer only to disposable test fixtures.
$StudyExistingCases = @(
  'tests/test_capture_recovery.py'
  'tests/test_research_storage.py::test_rollovers_reopen_pending_and_two_hour_continuation'
  'tests/test_research_storage.py::test_failed_transfer_last_source_checksum_and_recovery'
  'tests/test_research_storage.py::test_legacy_frozen_backup_versioned_limits_and_single_maintenance'
  'tests/test_research_storage.py::test_interrupted_segment_ack_recovery_and_consistent_rollups'
  'tests/test_research_storage.py::test_absence_mapping_access_and_quota_no_spill'
)
$env:PYTHONPATH = Join-Path $StudyCheckout 'src'
& $StudyPython -B -c "import psutil,pytest,sys; psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS); raise SystemExit(pytest.main(sys.argv[1:]))" `
  -q -p no:cacheprovider --tb=short --basetemp $AnotherNewPrivateTestDirectory `
  tests/test_compression_study.py @StudyExistingCases

# Final affected runner used these three node IDs (seven parametrized cases).
$StudyAffectedCases = @(
  'tests/test_compression_study.py::test_actual_process_interruption_is_recoverable_at_publish_boundaries'
  'tests/test_compression_study.py::test_concurrent_process_claim_refuses_work_and_releases_on_exit'
  'tests/test_compression_study.py::test_child_bootstrap_requires_exact_release_before_worker_side_effects'
)
$env:PYTHONPATH = ''
& $StudyPython -B -c "import psutil,pytest,sys; psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS); raise SystemExit(pytest.main(sys.argv[1:]))" `
  -q -p no:cacheprovider --tb=short --basetemp $ThirdNewPrivateTestDirectory @StudyAffectedCases

& $StudyPython -B -m ruff check --no-cache scripts/compression_study tests/test_compression_study.py
& $StudyPython -B -m mypy --platform win32 --follow-imports=silent `
  --ignore-missing-imports --cache-dir $PrivateTypeCache scripts/compression_study

$env:PYTHONPATH = Join-Path $StudyCheckout 'src'
& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 `
  --mode measure --repetitions 5 --seconds 900

& $StudyPython -B -m scripts.compression_study.run `
  --scratch $StudyScratch --owner-token $StudyOwnerToken --live-root $LiveResearchRoot `
  --base dcf7ccbb178cdd89175e427962dec80475620c73 `
  --mode smoke --repetitions 1 --seconds 300
```

The existing PR triggers can run normal hosted product gates. No workflow or
lockfile was edited, no Actions benchmark matrix was dispatched, and no whole
local suite, shared PostgreSQL service or frontend build was launched for this
lane. Hosted CI, installation, runtime acceptance, representative real samples,
quiet-window read latency and power-loss durability remain separate proof stages.

Benchmark-only. Operating storage and settings are unchanged.
No space has yet been reclaimed by this lane.
