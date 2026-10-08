# Q-Trades: code-to-product map

Use this map to build features, diagnose failures, find the responsible owner and
choose meaningful verification. Start with a symptom or workflow, then inspect
the linked current functions and their consumers before editing.

The reviewed application starting baseline is
`c92fe024b102ce0289066b84d4ad57bebd7bb7d8` (the PR87 source stack). The
[generated index](source-index.md) records current normalized file hashes and
exact reference locations. That source includes proposed research behavior beyond
the separately accepted installed `c653b136f4f0d4fac3f9855bbbb4c40b21a3c8a9`.
This map does not claim the stack is installed or research is currently enabled.
Refresh GitHub, the checked-out branch and installed receipts when investigating
operating behavior; a source map cannot identify a running process by itself.

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
