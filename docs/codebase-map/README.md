# Q-Trades: code-to-product map

Use this map to build features, diagnose failures, find the responsible owner and
choose meaningful verification. Start with a symptom or workflow, then inspect
the linked current functions and their consumers before editing.

The reviewed application starting baseline is
`9a8a2dfca533a3046ddbc9a651244bdc6d87bfbf` (merged PR91). The
[generated index](source-index.md) records current normalized file hashes and
exact reference locations. PR91's separately approved installation passed source
and selected-history preservation checks on October 8, with research paused.
Installed navigation exposed the chart/economics account mismatch recorded in
the [product ledger](../reviews/COHERENT_PRODUCT_66.md). Its reviewed account-scope
source successor is beyond that baseline and remains uninstalled. This map does
not activate research, establish model usefulness or authorize live operation.
Refresh GitHub, the checked-out branch and installed receipts when investigating
operating behavior; a source map cannot identify a running process by itself.

## Product handoffs and outstanding acceptance

The strict finite grant owns one original chain and at most three reserved model
requests. The later question/method policies are separate authorities with hourly
allowances, daily selection ceilings, one inference at a time and bounded active
work; hourly allowances are not a total experiment budget. Neither authority is
enabled by this map or by a passing source test.

| Handoff | Producer and actual consumer | Normal UI and durable recovery | Source status and remaining acceptance |
| --- | --- | --- | --- |
| Saved finding → current preparation | Scanner/daily captures → PatternComparisons → RoleWorker | Saved question links reopen the exact original wait/finding; current inputs have separate retained references | Bounded retained selection and wait recovery implemented. See [A1/A6 evidence](../reviews/CLOSED_LOOP_AUDIT.md). Installed recovery remains separate. |
| Proposal/rejection → next investigation | Worker review/dependency stages → method selector | Original task/verdict stays accessible; immutable selection owns its method | Scientific rejection or quiescent dependency can yield to the other offered method. Due work, unsafe/failed results and finite scope remain protected. See [scheduling](research-worker.md#selection-policies-and-fixed-methods). |
| Optional research → financial owner | AutonomousLab preparation → PaperStore/PaperEngine | Inbox and permanent reserve/fund/score receipts reconcile missing acknowledgments | Optional work releases the writer lock; fresh financial admission remains inside it. [Concurrency evidence](../reviews/CLOSED_LOOP_AUDIT.md) is disposable software proof. |
| Mature result → lesson → next question | Scored event → ResearchLessons → exact later role packet | Original task, lesson and next-task provenance | Source and fixture paths exist; actual authorized model interpretation and normal operating continuation remain unproved by this source checkpoint. |
| Fixed-rule result → stronger qualification | Exact original Lab reservation/score → existing paper_learning/financial writer | Original comparison opens a reviewed separate prospective candidate/control pair; exact account and source survive Back/reload | Implemented source. Frozen rules, implementation, costs, incumbent/control identity and capacity are enforced; 28 subsequent daily blocks and explicit designation remain required. No numeric artifact substitution. |
| Two methods → continuing refinement | p0/p1 catalog → supported strategy bank | Current selection states the two-method ceiling and retained exhausted work | Not implemented. Actual grounded p0/p1 acceptance precedes one justified versioned refinement; a different trial alone is not evidence of learning. |
| Reviewed examples → Training Lab preparation | Retained examples → existing preparation owner | Saved preparation preserves `trained=false` and `evaluated=false` | Intentional preparation boundary. Training/evaluation needs its own applicable authorization. |

The [coherent product ledger](../reviews/COHERENT_PRODUCT_66.md) records the current
workflow and proof stages. The [audit repair ledger](../reviews/CLOSED_LOOP_AUDIT.md)
records earlier checks and their limits. Code present, source tests, installed operation, actual model
usefulness and prospective economics are five different claims.

## Find the right workflow

| Work or symptom | Guide |
| --- | --- |
| Understand startup, background workers and data ownership | [Architecture](architecture.md) |
| Missing/stale prices, a wide universe, public feed resync | [Market data](market-data.md) |
| Historical preparation, daily picks, chart patterns, levels and alerts | [Scanner and charts](scanner-charts.md) |
| A panel is missing, a control conflicts, request/response wiring | [Dashboard and API](dashboard-api.md) |
| Orders, reservations, fees, account counts, risk and trade history | [Paper accounting](paper-accounting.md) |
| Strategy bank, deterministic learning, preserved trials and comparisons | [Strategy experiments](strategy-experiments.md) |
| Options, stocks and other descriptive/replay research | [Secondary research](secondary-research.md) |
| What directs the researcher, retained questions, attempts and lessons | [Research worker](research-worker.md) |
| Model refusal, token limits, child resources and recovery | [Model admission](model-admission.md) |
| Evidence, recording, memory, Library/Reviews and separate Training Lab | [Evidence, storage and training](evidence-storage-training.md) |
| MCP access, actor scopes, registered tools and tool requests | [Oversight and tools](oversight-tools.md) |
| Launcher, scheduled task, process identity, updater and release evidence | [Runtime and updates](runtime-updates.md) |
| Which check proves a change; what remains untested | [Verification and coverage](verification.md) |
| Update this map without obscuring drift | [Maintenance](maintenance.md) |
| Locate every tracked program/test/config file, declaration or API route | [Source index](source-index.md) |

## Use the navigation tool

From the repository root, use an available Python 3.12+ interpreter. The tool uses
the standard library and read-only Git commands. Query/check commands inspect this
checkout's source and map; they do not import the trading application or contact
the service, database, venue, model or another project.

```text
python tools/codebase_map.py --tasks
python tools/codebase_map.py --lookup PaperStore
python tools/codebase_map.py --lookup PatternScanner
python tools/codebase_map.py --dependencies src/trading/paper_store.py
python tools/codebase_map.py --routes --json
python tools/codebase_map.py --inventory --json
python tools/codebase_map.py --task runtime-update-mismatch
python tools/codebase_map.py --trace runtime-updates.md#updater-target-and-preservation
python tools/codebase_map.py --affected
python tools/codebase_map.py --check
```

`--lookup` searches declarations, paths, reviewed references and troubleshooting
tasks. `--task` exports a named investigation and its selected current anchors.
`--trace` exports exactly the chosen guide/heading and descendants, including its
linked source references; it does not recursively pull in every linked document.
`--dependencies` reports declared local imports and consumers. Imports, decorator
registrations and lexical declarations help navigation; read the actual call and
state transition to establish behavior.

Snapshot-wide lookup, inventory, routes and dependencies require a current corpus,
so a new consumer or route cannot be silently omitted. `--affected` reports source,
guide and map-definition drift. A selected task/trace can still inspect its
unchanged sources while unrelated existing source is being edited, but refuses
changed guide/reference definitions or inventory. Review and explicitly refresh
the map when needed; it never updates its own baseline during a query.

## What comprehensive coverage means

Every tracked executable source, frontend source/style, test/fixture, script,
application/build configuration and dependency file in the declared inventory
has an explicit area and guide. Python declarations and literal API registrations
are indexed automatically. The workflow guides explain the application's main
state, data and authority handoffs, including failures and recovery.

Historical evidence/document artifacts, private/ignored operating files, external
model weights and dependency/vendor directories are outside the source inventory.
Their actual owners and relevant read paths are mapped. The coverage inventory
does not imply every branch or hypothesis received runtime acceptance.

Use these evidence labels consistently:

- **Declared:** a symbol, import, route or registration exists in source.
- **Source-linked:** inspected assignments/calls connect the named owners.
- **Covered by tests:** a named test addresses behavior; inspect its conditions and skips.
- **Observed:** an explicitly identified retained execution exercised behavior.

A map check establishes reference/inventory/link freshness. Financial preservation,
model usefulness, installed coexistence, prospective economics and normal user
workflow acceptance require their corresponding evidence. Missing map coverage is
an investigation gap, not evidence that code is unused or safe to remove.
