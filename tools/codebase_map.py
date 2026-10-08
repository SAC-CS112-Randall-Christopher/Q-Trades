"""Navigate Q-Trades source and validate its reviewed code-to-product map.

Uses only the Python standard library and read-only Git commands. No application
imports, model calls, network, databases, or runtime control. --refresh writes
only the reviewed source snapshot and its deterministic generated index.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MAP = "docs/codebase-map"
SNAPSHOT = f"{MAP}/source-refs.json"
INDEX = f"{MAP}/source-index.md"
SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".cjs",
    ".mjs",
    ".cs",
    ".ps1",
    ".cmd",
    ".toml",
    ".json",
    ".yml",
    ".yaml",
}
PREFIXES = ("src/", "scripts/", "tools/", "tests/", "configs/", "apps/web/", ".github/")
EXTRA = {"pyproject.toml", "requirements-lock.txt", "README.md", "AGENTS.md", ".gitignore"}


class MapError(ValueError):
    """An invalid or incomplete map must remain visible."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30)
    if result.returncode:
        raise MapError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8")


def local(root: Path, relative: str) -> Path:
    path = root / relative
    if not relative or "\\" in relative or Path(relative).is_absolute():
        raise MapError(f"Not a repository-relative path: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise MapError(f"Path escapes repository: {relative}")
    return path


def read(root: Path, relative: str) -> str:
    try:
        return local(root, relative).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except (OSError, UnicodeError) as error:
        raise MapError(f"Cannot read {relative}: {error}") from error


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tracked_source(root: Path) -> list[str]:
    paths = git(root, "ls-files", "-z").split("\0")
    return sorted(
        path
        for path in paths
        if path
        and (
            path in EXTRA
            or (
                (path.startswith(PREFIXES) or "/" not in path)
                and Path(path).suffix.lower() in SUFFIXES
            )
        )
    )


def declarations(path: str, text: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if path.endswith(".py"):
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as error:
            raise MapError(f"Cannot parse {path}: {error}") from error

        def visit(node: ast.AST, prefix: str = "") -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = prefix + child.name
                    found.append(
                        {
                            "name": name,
                            "line": child.lineno,
                            "kind": "class" if isinstance(child, ast.ClassDef) else "function",
                        }
                    )
                    visit(child, name + ".")
                else:
                    visit(child, prefix)

        visit(tree)
    else:
        patterns = {
            ".ps1": r"^\s*function\s+([\w-]+)",
            ".cs": r"\b(?:class|struct|enum)\s+(\w+)",
            ".ts": r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type)\s+(\w+)",
            ".tsx": r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type)\s+(\w+)",
            ".cjs": r"^\s*(?:async\s+)?function\s+(\w+)",
            ".mjs": r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        }
        pattern = patterns.get(Path(path).suffix.lower())
        if pattern:
            for number, line in enumerate(text.splitlines(), 1):
                for match in re.finditer(pattern, line):
                    found.append(
                        {"name": match.group(1), "line": number, "kind": "lexical declaration"}
                    )
    return found


def routes(path: str, text: str) -> list[dict[str, Any]]:
    if not path.endswith(".py"):
        return []
    tree = ast.parse(text, filename=path)
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"}:
                continue
            if (
                decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                result.append(
                    {
                        "method": method,
                        "route": decorator.args[0].value,
                        "handler": node.name,
                        "line": node.lineno,
                    }
                )
    return sorted(result, key=lambda value: (value["route"], value["method"]))


def imports(path: str, text: str) -> list[str]:
    """Declared imports only; these are not execution or inferred call edges."""
    found: set[str] = set()
    if path.endswith(".py"):
        package = path.removeprefix("src/").removesuffix(".py").split("/")[:-1]
        for node in ast.walk(ast.parse(text, filename=path)):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = package[: len(package) - node.level + 1] if node.level else []
                module = ".".join(prefix + ([node.module] if node.module else []))
                if module:
                    found.add(module)
                    found.update(module + "." + alias.name for alias in node.names)
    elif Path(path).suffix in {".tsx", ".ts", ".mjs", ".cjs"}:
        found.update(re.findall(r"""\bfrom\s+["']([^"']+)["']""", text))
        found.update(re.findall(r"""\brequire\(["']([^"']+)["']\)""", text))
        found.update(re.findall(r"""\bimport\s*(?:\(\s*)?["']([^"']+)["']""", text))
    return sorted(found)


def load_parts(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    directory = local(root, f"{MAP}/parts")
    for path in sorted(directory.glob("*.json")):
        part = json.loads(read(root, path.relative_to(root).as_posix()))
        if set(part) != {"references", "tasks"}:
            raise MapError(f"Part keys must be references/tasks: {path.name}")
        refs.extend(part["references"])
        tasks.extend(part["tasks"])
    if not refs or not tasks:
        raise MapError("Map requires reviewed references and troubleshooting tasks")
    for label, entries in (("reference", refs), ("task", tasks)):
        ids = [entry["id"] for entry in entries]
        if len(set(ids)) != len(ids):
            raise MapError(f"Duplicate {label} IDs")
        if any(not re.fullmatch(r"[a-z][a-z0-9-]*", value) for value in ids):
            raise MapError(f"Invalid {label} ID")
    return sorted(refs, key=lambda item: item["id"]), sorted(tasks, key=lambda item: item["id"])


def ref_line(root: Path, ref: dict[str, Any]) -> int:
    text = read(root, ref["path"])
    if "symbol" in ref and "anchor" in ref:
        raise MapError(f"Reference has both symbol and literal: {ref['id']}")
    if "symbol" in ref:
        hits = [
            entry for entry in declarations(ref["path"], text) if entry["name"] == ref["symbol"]
        ]
        if len(hits) != 1:
            raise MapError(
                f"Expected one declaration for {ref['id']}: {ref['symbol']}, found {len(hits)}"
            )
        return int(hits[0]["line"])
    if "anchor" in ref:
        if not ref["anchor"] or text.count(ref["anchor"]) != 1:
            raise MapError(f"Missing or ambiguous literal for {ref['id']}")
        return text[: text.index(ref["anchor"])].count("\n") + 1
    return 1


def headings(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    counts: dict[str, int] = {}
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
        if fenced:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        value = re.sub(r"[^\w\s-]", "", match.group(1).lower()).replace(" ", "-")
        count = counts.get(value, 0)
        counts[value] = count + 1
        result[value + (f"-{count}" if count else "")] = number
    # Explicit generated anchors support stable reference IDs.
    for match in re.finditer(r'<a id="([a-z][a-z0-9-]*)"></a>', text):
        result[match.group(1)] = text[: match.start()].count("\n") + 1
    return result


def guide_section(root: Path, task: dict[str, Any]) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]*\.md", task["guide"]):
        raise MapError(f"Trace must name a code-map guide: {task['guide']}")
    text = read(root, f"{MAP}/{task['guide']}")
    if not task.get("section"):
        return text
    slug = task["section"]
    anchors = headings(text)
    if slug not in anchors:
        raise MapError(f"Missing task section {task['id']}: {slug}")
    lines = text.splitlines()
    start = anchors[slug] - 1
    depth = len(lines[start]) - len(lines[start].lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s", lines[index])
        if match and len(match.group(1)) <= depth:
            end = index
            break
    return "\n".join(lines[start:end]) + "\n"


def area(config: list[dict[str, Any]], path: str) -> tuple[str, str]:
    matches = [
        entry
        for entry in config
        if path in entry.get("paths", [])
        or any(re.fullmatch(pattern, path) for pattern in entry.get("patterns", []))
    ]
    if len(matches) != 1:
        raise MapError(f"Expected one inventory area for {path}; found {len(matches)}")
    return matches[0]["id"], matches[0]["guide"]


def capture(root: Path, baseline: str) -> dict[str, Any]:
    refs, tasks = load_parts(root)
    areas = json.loads(read(root, f"{MAP}/areas.json"))
    files: list[dict[str, Any]] = []
    tracked = set(tracked_source(root))
    for path in sorted(tracked):
        text = read(root, path)
        owner, guide = area(areas, path)
        files.append(
            {
                "path": path,
                "sha256": sha(text),
                "area": owner,
                "guide": guide,
                "declarations": declarations(path, text),
                "routes": routes(path, text),
                "imports": imports(path, text),
            }
        )
    modules = {
        entry["path"].removeprefix("src/").removesuffix(".py").replace("/", "."): entry["path"]
        for entry in files
        if entry["path"].endswith(".py")
    }
    all_paths = {entry["path"] for entry in files}
    for entry in files:
        dependencies = set()
        for module in entry["imports"]:
            if module in modules:
                dependencies.add(modules[module])
            if module.startswith(".") and not entry["path"].endswith(".py"):
                base = (Path(entry["path"]).parent / module).as_posix()
                for suffix in ("", ".tsx", ".ts", ".css", ".mjs", ".cjs"):
                    # Resolve ./ and ../ without allowing a file outside this root.
                    candidate = local(root, base + suffix).resolve().relative_to(root).as_posix()
                    if candidate in all_paths:
                        dependencies.add(candidate)
        entry["local_imports"] = sorted(dependencies)
    for ref in refs:
        if ref["path"] not in tracked:
            raise MapError(f"Reference must point to tracked inventory: {ref['id']}")
        ref["line"] = ref_line(root, ref)
    ids = {ref["id"] for ref in refs}
    for task in tasks:
        missing = set(task["references"]) - ids
        if missing:
            raise MapError(f"Unknown task references: {task['id']}: {sorted(missing)}")
        guide_section(root, task)
    guides = {
        path.relative_to(root).as_posix(): sha(read(root, path.relative_to(root).as_posix()))
        for path in sorted(local(root, MAP).glob("*.md"))
        if path.name != "source-index.md"
    }
    return {
        "schema": 1,
        "baseline_commit": baseline,
        "files": files,
        "references": refs,
        "tasks": tasks,
        "guides": guides,
        "areas": areas,
    }


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Generated source index",
        "",
        f"Application starting baseline: `{snapshot['baseline_commit']}`.",
        "",
        "Generated by `python tools/codebase_map.py --refresh` after reviewing the map.",
        "File hashes describe the reviewed working tree, including this map's development tooling.",
        "Python declarations use AST; other declaration listings are lexical navigation.",
        "Routes list literal decorator registrations; inspect runtime reachability and permission.",
        "Inventory coverage is distinct from curated workflow coverage and executed verification.",
        "",
        "## Reviewed references",
        "",
    ]
    for ref in snapshot["references"]:
        lines.extend(
            [
                f'<a id="{ref["id"]}"></a>',
                f"### {ref['id']}",
                "",
                f"{ref['description']} — "
                f"[{ref['path']}:{ref['line']}](../../{ref['path']}#L{ref['line']})",
                "",
            ]
        )
    lines.extend(
        [
            "## Complete tracked inventory",
            "",
            "| File | Area / guide | Declarations |",
            "| --- | --- | --- |",
        ]
    )
    for file in snapshot["files"]:
        lines.append(
            f"| [{file['path']}](../../{file['path']}) | [{file['area']}]({file['guide']}) "
            f"| {len(file['declarations'])} |"
        )
    lines.extend(
        [
            "",
            "## API registrations",
            "",
            "| Method | Route | Source handler |",
            "| --- | --- | --- |",
        ]
    )
    for file in snapshot["files"]:
        for route in file["routes"]:
            lines.append(
                f"| {route['method']} | `{route['route']}` | "
                f"[{route['handler']}](../../{file['path']}#L{route['line']}) |"
            )
    lines.extend(["", "## Declaration index", ""])
    for file in snapshot["files"]:
        if not file["declarations"]:
            continue
        lines.extend([f"### {file['path']}", ""])
        for decl in file["declarations"]:
            lines.append(
                f"- [{decl['name']}](../../{file['path']}#L{decl['line']}) — {decl['kind']}"
            )
        if file["local_imports"]:
            lines.append(
                "Declared local imports: "
                + ", ".join(f"[{path}](../../{path})" for path in file["local_imports"])
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def linked_source_refs(snapshot: dict[str, Any], text: str) -> set[str]:
    """Index headings are navigation; only reviewed reference IDs identify source."""
    linked = set(re.findall(r"\[[^\]]*\]\(source-index\.md#([^\s)]+)\)", text))
    unknown = linked - headings(render(snapshot)).keys()
    if unknown:
        raise MapError("Unknown source-index fragments: " + ", ".join(sorted(unknown)))
    return linked & {ref["id"] for ref in snapshot["references"]}


def link_errors(root: Path, overrides: dict[str, str] | None = None) -> list[str]:
    errors = []
    overrides = overrides or {}
    directory = local(root, MAP)
    paths = set(directory.glob("*.md")) | {local(root, path) for path in overrides}
    for path in sorted(paths):
        relative_path = path.relative_to(root).as_posix()
        text = overrides.get(relative_path)
        if text is None:
            text = read(root, relative_path)
        for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", text):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            relative, _, fragment = target.partition("#")
            dest = (path.parent / relative).resolve() if relative else path
            if not dest.is_relative_to(root.resolve()):
                errors.append(f"{path.name}: outside local link {target}")
                continue
            dest_text = overrides.get(dest.relative_to(root).as_posix())
            if dest_text is None and not dest.is_file():
                errors.append(f"{path.name}: missing/outside local link {target}")
            elif fragment:
                if dest_text is None:
                    dest_text = dest.read_text(encoding="utf-8-sig")
                if re.fullmatch(r"L[1-9]\d*", fragment):
                    if int(fragment[1:]) > len(dest_text.splitlines()):
                        errors.append(f"{path.name}: missing source line {target}")
                elif fragment not in headings(dest_text):
                    errors.append(f"{path.name}: missing fragment {target}")
    return errors


def differences(root: Path, saved: dict[str, Any]) -> list[str]:
    old = {entry["path"]: entry for entry in saved["files"]}
    current = set(tracked_source(root))
    changed = [f"ADDED {path}" for path in sorted(current - old.keys())]
    changed.extend(f"REMOVED {path}" for path in sorted(old.keys() - current))
    for path in sorted(current & old.keys()):
        if sha(read(root, path)) != old[path]["sha256"]:
            changed.append(f"CHANGED {path}")
    old_guides = saved.get("guides", {})
    current_guides = {
        path.relative_to(root).as_posix()
        for path in local(root, MAP).glob("*.md")
        if path.name != "source-index.md"
    }
    changed.extend(f"GUIDE ADDED {path}" for path in sorted(current_guides - old_guides.keys()))
    changed.extend(f"GUIDE REMOVED {path}" for path in sorted(old_guides.keys() - current_guides))
    for path in sorted(current_guides & old_guides.keys()):
        if sha(read(root, path)) != old_guides[path]:
            changed.append(f"GUIDE CHANGED {path}")
    current_refs, current_tasks = load_parts(root)
    old_refs = [
        {key: value for key, value in ref.items() if key != "line"} for ref in saved["references"]
    ]
    if current_refs != old_refs or current_tasks != saved["tasks"]:
        changed.append("MAP reference/task definitions changed")
    if json.loads(read(root, f"{MAP}/areas.json")) != saved.get("areas"):
        changed.append("MAP inventory area definitions changed")
    return changed


def validate(root: Path, saved: dict[str, Any]) -> list[str]:
    errors = differences(root, saved)
    try:
        current = capture(root, saved["baseline_commit"])
        if current != saved:
            errors.append("Map metadata/declarations/tasks changed; review before refreshing")
        if render(saved) != read(root, INDEX):
            errors.append("Generated source index differs from reviewed snapshot")
        errors.extend(link_errors(root))
    except (MapError, KeyError, json.JSONDecodeError) as error:
        errors.append(str(error))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    for flag in ("check", "affected", "tasks", "inventory", "routes", "refresh"):
        actions.add_argument(f"--{flag}", action="store_true")
    for flag in ("lookup", "task", "trace", "dependencies"):
        actions.add_argument(f"--{flag}")
    parser.add_argument("--baseline", help="Immutable commit for a reviewed --refresh only")
    parser.add_argument("--json", action="store_true", help="Machine-readable query/check result")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result: Any
    try:
        if args.refresh:
            if not args.baseline or not re.fullmatch(r"[0-9a-f]{40}", args.baseline):
                raise MapError("--refresh requires --baseline with a reviewed full commit SHA")
            git(root, "cat-file", "-e", args.baseline + "^{commit}")
            snapshot = capture(root, args.baseline)
            generated = render(snapshot)
            errors = link_errors(root, {INDEX: generated})
            if errors:
                raise MapError("\n".join(errors))
            # Resolve declarations and task sections before touching either output.
            local(root, SNAPSHOT).write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            local(root, INDEX).write_text(generated, encoding="utf-8")
            print(
                f"Reviewed snapshot: {len(snapshot['files'])} files, "
                f"{len(snapshot['references'])} references, {len(snapshot['tasks'])} tasks"
            )
            return 0
        saved = json.loads(read(root, SNAPSHOT))
        if args.check or args.affected:
            errors = validate(root, saved) if args.check else differences(root, saved)
            result = {
                "ok": not errors,
                "changes": errors,
                "files": len(saved["files"]),
                "references": len(saved["references"]),
                "tasks": len(saved["tasks"]),
            }
            print(
                json.dumps(result, indent=2)
                if args.json
                else (
                    "\n".join(errors)
                    or "Map is current; all inventory, references, tasks and local links checked."
                )
            )
            return 1 if errors else 0
        # Query selected current anchors. A stale snapshot is visible; no auto-refresh.
        current_refs, current_tasks = load_parts(root)
        saved_refs = [
            {key: value for key, value in ref.items() if key != "line"}
            for ref in saved["references"]
        ]
        if current_refs != saved_refs or current_tasks != saved["tasks"]:
            raise MapError(
                "Map reference/task metadata changed; review and refresh before querying"
            )
        if set(tracked_source(root)) != {entry["path"] for entry in saved["files"]}:
            raise MapError(
                "Tracked inventory changed; run --affected and review new/removed coverage"
            )
        if args.lookup or args.routes or args.inventory or args.dependencies:
            changes = differences(root, saved)
            if changes:
                raise MapError(
                    "Snapshot-wide query is stale; run --affected and review: " + "; ".join(changes)
                )
        refs = {entry["id"]: entry for entry in saved["references"]}
        if args.tasks:
            result = saved["tasks"]
        elif args.inventory:
            result = [
                {key: entry[key] for key in ("path", "area", "guide")} for entry in saved["files"]
            ]
        elif args.routes:
            result = [
                {"path": entry["path"], **route}
                for entry in saved["files"]
                for route in entry["routes"]
            ]
        elif args.dependencies:
            selected = [entry for entry in saved["files"] if entry["path"] == args.dependencies]
            if len(selected) != 1:
                raise MapError(f"Unknown inventory path: {args.dependencies}")
            result = {
                "path": args.dependencies,
                "imports": selected[0]["local_imports"],
                "declared_consumers": [
                    entry["path"]
                    for entry in saved["files"]
                    if args.dependencies in entry["local_imports"]
                ],
                "meaning": "Declared static imports only; inspect actual calls and ownership",
            }
        elif args.lookup:
            query = args.lookup.casefold()
            result = {
                "references": [
                    ref for ref in saved["references"] if query in json.dumps(ref).casefold()
                ],
                "declarations": [
                    {"path": entry["path"], **decl}
                    for entry in saved["files"]
                    for decl in entry["declarations"]
                    if query in (entry["path"] + " " + decl["name"]).casefold()
                ],
                "files": [
                    {key: entry[key] for key in ("path", "area", "guide")}
                    for entry in saved["files"]
                    if query in entry["path"].casefold()
                ],
                "tasks": [task for task in saved["tasks"] if query in json.dumps(task).casefold()],
            }
            matched_refs = {ref["id"] for ref in result["references"]}
            result["tasks"] = [
                task
                for task in saved["tasks"]
                if query in json.dumps(task).casefold()
                or matched_refs.intersection(task["references"])
            ]
            if not any(result.values()):
                raise MapError(
                    f"No mapped match: {args.lookup}; inspect source and add missing coverage"
                )
        else:
            if args.task:
                matches = [task for task in saved["tasks"] if task["id"] == args.task]
                if len(matches) != 1:
                    raise MapError(f"Unknown task: {args.task}")
                task = matches[0]
                selected_text = guide_section(root, task)
                task = dict(task)
            else:
                guide, _, section = args.trace.partition("#")
                task = {"guide": guide, "section": section}
                selected_text = guide_section(root, task)
                matches = [
                    item
                    for item in saved["tasks"]
                    if item["guide"] == guide and (not section or item.get("section") == section)
                ]
                task["references"] = sorted({ref for item in matches for ref in item["references"]})
            task["references"] = sorted(
                set(task["references"]) | linked_source_refs(saved, selected_text)
            )
            if not args.task:
                if not task["references"]:
                    raise MapError(
                        "Trace has no reviewed source references; use a mapped workflow section"
                    )
            selected = []
            guide_path = f"{MAP}/{task['guide']}"
            if sha(read(root, guide_path)) != saved["guides"].get(guide_path):
                raise MapError(f"Stale selected guide: {task['guide']}; review and refresh")
            file_pins = {file["path"]: file["sha256"] for file in saved["files"]}
            for name in task["references"]:
                ref = dict(refs[name])
                if sha(read(root, ref["path"])) != file_pins[ref["path"]]:
                    raise MapError(
                        f"Stale selected source: {ref['path']}; run --affected and review"
                    )
                ref["line"] = ref_line(root, ref)
                selected.append(ref)
            result = {
                "guide": task["guide"],
                "section": task.get("section"),
                "text": guide_section(root, task),
                "references": selected,
            }
        # Never emit historical line locations as current when selected source changed.
        selected_paths: set[str] = set()
        if args.lookup:
            for field in ("references", "declarations", "files"):
                selected_paths.update(item["path"] for item in result[field])
        elif args.dependencies:
            selected_paths = {args.dependencies, *result["imports"], *result["declared_consumers"]}
        elif args.routes:
            selected_paths = {item["path"] for item in result}
        elif args.inventory:
            selected_paths = set(tracked_source(root)) | {item["path"] for item in result}
        pins = {entry["path"]: entry["sha256"] for entry in saved["files"]}
        for path in sorted(selected_paths):
            if path not in pins or sha(read(root, path)) != pins[path]:
                raise MapError(f"Stale selected source: {path}; run --affected and review")
        print(
            json.dumps(result, indent=2)
            if args.json
            else json.dumps(result, indent=2, ensure_ascii=True)
        )
        return 0
    except (MapError, OSError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"Code map refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
