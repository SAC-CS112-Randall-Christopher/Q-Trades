# Verification, coverage and proof limits

## Choose the check that covers the outcome

The [hosted workflow](source-index.md#verification-workflow) separates native
Windows behavior, slower research recovery, dashboard build, process/update
ownership, real disposable PostgreSQL integration, browser workflows and
persistent-research recovery. The separate [map workflow](source-index.md#map-workflow)
checks every PR and main push using Python alone, including guide/tool-only changes.
Read exact selectors and lifecycle budgets;
passing one job does not substitute for another job or installed acceptance.

| Changed path | Relevant first evidence | Broader evidence when justified |
| --- | --- | --- |
| Code-map/tooling only | Map `--check`, tool tests, docs/source-reference review, lint | Exact-head code-map CI; application source proof retained if inputs unchanged |
| Financial engine/store | Focused accounting/risk/history tests and disposable persistence | Full PostgreSQL suite and changed normal Accounts/history workflow |
| Scanner/chart UI | Source/fixture tests, typecheck/build, compiled browser cases | Exact-head browser and persistent-research jobs |
| Research worker/model admission | Contract/attempt/recovery tests, synthetic boundary tests | Authorized actual tokenizer/model/coexistence evidence separately |
| Storage/archive/knowledge | Owner/quota/cold-read/cancellation/failure tests | Real disposable stores and changed Library/Reviews workflow |
| Task/process/updater | Ownership, exact-target and shutdown tests | Separately authorized installed preservation/restart/workflow receipt |

All [test and fixture files](source-index.md#complete-tracked-inventory) are included
in the inventory, with declaration lookup for exact test functions. For a workflow,
its guide lists relevant covering tests. Inspect fixture setup, actual dependencies,
assertions and skips before deciding the check applies to a change.

## Existing check commands

The [package configuration](source-index.md#platform-package) declares pytest,
Ruff, strict mypy and the source/test paths. Available local environments can run
the existing checks; do not acquire dependencies or start operating services as
part of map navigation.

```text
python tools/codebase_map.py --check
python -m unittest discover -s tests -p test_codebase_map.py
python -m ruff check tools/codebase_map.py tests/test_codebase_map.py
python -m mypy tools/codebase_map.py
```

Application checks remain the existing pytest/component workflow. Windows pytest
uses fresh task-owned temporary directories and disables the cache provider under
the current repository instructions. A missing `QTRADES_TEST_DATABASE` produces
explicit skips; that run is not database persistence proof. Preserve failed setup,
fixture, hosted and runtime receipts even when a later corrected case passes.

## Evidence dimensions

The map deliberately keeps these separate:

1. Inventory and source-reference freshness.
2. Static declarations/imports/routes.
3. Inspected call/state/authority handoffs.
4. Focused synthetic software checks.
5. Real disposable database/backend/browser checks.
6. Exact-head hosted checks and independent review.
7. Merge, installation and operating preservation/normal-workflow acceptance.
8. Actual model capacity/coexistence/usefulness and prospective trading economics.

The existing source stack's earlier passing checks belong to their exact source
inputs. This map's baseline starts at PR87; adding documentation does not relabel
old executions as a fresh installed result. A runtime installation marker is not
proof that all files and preserved data match; a green test is not a profitable
strategy, continuous observation window or qualified model.

## Coverage audit and remaining uncertainty

The map checker verifies the full declared inventory has exactly one explicit
area/guide; reviewed references resolve to one declaration/literal; task references
and headings exist; source hashes and generated index match; local links resolve.
`--lookup`, `--dependencies` and `--routes` are navigation surfaces. The index's
automatic declaration/import extraction is labeled as such and never asserted to
be an execution graph.

Curated workflow coverage includes market ingestion, scanner/daily analysis/charts,
paper/accounting/risk/history, deterministic and role-led experiments, models and
resources, evidence/replay/memory/knowledge/training, scoped oversight, secondary
research, dashboard/API and Windows delivery/ownership. Read each guide's gaps.

Current operating activation, direct NAT writer mapping, populated Library/Reviews,
prospective strategy success and clean-machine native packaging require their own
evidence. A fresh code map does not fill those gaps.
