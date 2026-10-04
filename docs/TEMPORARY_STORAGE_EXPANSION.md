# Reviewed temporary storage increase: 400 decimal GB

Chris requested 400 GB total for the existing Q-Trades temporary research tier
on October 3, 2026. This is 400,000,000,000 bytes, an increase of 300 GB. Retained
research stays at 100 GB. This changes a quota, not a disk partition or SQL Server
tempdb. Fresh declarations continue to default to 100 GB per tier.

The existing installed plan and owned-root marker are frozen together. Changing
JSON alone is refused. The explicit successor keeps the root/volume, reserves,
scratch/segment sizes, retention and housekeeping unchanged. It saves original
metadata in a bounded private successor receipt before replacing either file.
No segment, evidence record, index, account or financial row is rewritten.

From the existing GitHub checkout, the reviewed updater invocation is:

```powershell
.\scripts\Update-QTrades.ps1 -TemporaryStorageGB 400 -ExpectedTemporaryStorageGB 100
```

It previews while the app runs, builds before stopping, uses the existing verified
owned-process shutdown and supervisor mutex, installs reviewed main, applies the
successor under the financial writer's advisory lock, then restarts normally.
Default updates do not change quotas. A live writer, wrong identity/marker,
different current quota, redirected metadata or inadequate free disk space
refuses the transition. Both target and expected previous quota are required.

The fixed helper can also preview without changing the running service:

```powershell
<EXISTING_PYTHON> scripts/configure_research_storage.py `
  --settings <INSTALLED_DATA>/paper-database.json --directory <INSTALLED_DATA> `
  --temporary-gb 400 --expected-temporary-gb 100
```

`--apply` is reserved for the authorized stopped-writer update. A disconnect
between marker/plan replacement fails closed. Preserve its successor receipt and
original bytes; retry the same explicit updater parameters to complete the
recorded transition. Do not remove evidence or synthesize a fresh ownership
marker. A repeated completed transition is idempotent. Partial staging files
remain visible for diagnosis.

Source/QA receipts are recorded in the owning PR. Before installation, retain
private source/config and account/history checks. After restart, verify actual
`/api/research/storage` worker receipts report 400 GB temporary / 100 GB retained,
and inspect the normal AI Lab storage panel. A saved successor or passing test
does not establish active capture, uninterrupted market coverage, inference
admission, model quality or strategy improvement. Merge/install/restart remain
subject to the existing explicit approval process; unrelated PRs are excluded.

## October 3 source verification

Native Windows Python 3.12.10 and an owned disposable PostgreSQL 17 cluster:
**58 passed, 1 skipped**, 88.09 seconds. The selection includes research storage,
the expansion helper, actual stopped/live financial-writer checks, unchanged
financial state/events, original evidence reopen, the normal storage API,
interrupted metadata recovery/idempotence, and native PowerShell updater paths.
The single skip is actual symlink creation requiring Windows developer mode;
that OS-level path case is not claimed verified. Whole-repo Ruff and strict mypy
passed (88 source files). New tests are in the hosted Windows selection.

Capacity in the finite fixtures is simulated. No 400 GB allocation, volume
throughput, full-disk load or new market-capture window was performed. The real
installed configuration/owned marker passed a read-only successor preview, with
about 1.3 TB free on the declared volume. It confirms feasibility, not activation.
No operating configuration, marker, evidence or financial rows were changed.

The first native run was **1 failed, 57 passed, 1 skipped**. Its preservation
assertion caught Windows newline normalization of the archived original plan.
The helper now retains exact original text bytes; the corrected selection above
passed. Original failed/final receipts remain private. The existing Starlette/
httpx deprecation warning remains visible. Hosted and installed acceptance are
separate stages; their exact-source outcomes are recorded in the owning PR.
