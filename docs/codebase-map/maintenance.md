# Map maintenance and implementation contract

## Keep behavior and navigation together

The developer changing a behavior owns the guide/reference/task update in the same
PR. Read the map on the branch being investigated. Reconcile the meaning of both
sides when combining source changes; blindly refreshing hashes cannot resolve a
changed financial or authorization handoff.

1. Run `python tools/codebase_map.py --affected` to see added, changed and removed
   tracked source inputs. Unmapped new files remain visible.
2. Read the current assigning function, actual consumer, failure/recovery owner and
   applicable tests. Update the relevant guide and `parts/*.json` entries.
3. Assign added files explicitly in `areas.json`; inspect removed coverage rather
   than silently treating it as irrelevant.
4. After review, refresh with the full immutable application starting baseline:
   `python tools/codebase_map.py --refresh --baseline <full-reviewed-SHA>`.
5. Run `--check`, tool tests and affected application verification. Commit the
   guides, JSON parts/areas, snapshot and generated index together.

`--refresh` explicitly writes only `source-refs.json` and `source-index.md`. It is a
maintenance operation after review, not a query command or automatic acceptance
of source drift. The baseline identifies where this source increment starts;
normalized file hashes bind its reviewed working-tree content, including the new
development tool. Final PR/commit identity and checks remain separate evidence.

## Data model

[The tool](source-index.md#map-tool) loads small JSON parts with `references` and
`tasks`. A reference has a stable ID, repository path, description and optional
within-file Python declaration (`Class.method` / `create_app.route_handler`) or
one unique literal anchor. Whole-file wiring references are permitted. A reference
cannot use both symbol and literal, and ambiguous/missing anchors refuse validation.

Tasks name a guide and optional heading plus source/test reference IDs and symptom
phrases. The tool exports selected text and exact current anchors. The explicit
`areas.json` assigns every inventory file to exactly one workflow guide. Generated
snapshot/index files are reproducible; curated guides and descriptions require
human/code review.

## Freshness and Windows newlines

File fingerprints normalize UTF-8 BOM and CRLF/LF differences, which Git checkouts
may change without modifying code. They still detect semantic/comment/whitespace
edits after normalization. Stable IDs point to declarations/literals rather than
assuming historical line numbers are current. Generated links include resolved
line locations for source browsing.

Missing files, moved/duplicate declarations, stale source, added inventory,
changed tasks/areas, broken guide links and edited generated output stay visible.
No application imports are needed to check symbols; Python uses AST. TypeScript,
PowerShell, C# and browser-script declaration listings are lexical and explicitly
limited; reviewed literal anchors provide exact navigation when needed.

## Scope and operation

The tool reads tracked source in this repository plus its map. Git calls are
read-only and use structured arguments; root-relative paths are checked against
the repository. It creates no source database, service, model index, credentials,
network connection or application process. Private/ignored operating stores and
another project's data stay outside the map inventory.

The [tool tests](source-index.md#map-tool-tests) exercise positive navigation and
negative stale/missing/ambiguous/escaping/link/schema cases against tiny isolated
Git fixtures. Those tests verify the map tool, not trading behavior. The dedicated
CI job needs only checkout and Python; existing application jobs remain unchanged.

## Review checklist

- Does the explanation name the assigning owner, consumer, persistence and recovery?
- Are declarations/imports distinguished from actual inspected calls?
- Are rules, configuration, experimental thresholds and measured limits described accurately?
- Do test links cover the claimed behavior, with real versus synthetic/skip scope visible?
- Are source candidate, installed identity and operating authorization kept distinct?
- Are all new executable/config/test files inventoried and mapped?
- Does `--check` pass on the reviewed combined source, without concealing changed meaning?
