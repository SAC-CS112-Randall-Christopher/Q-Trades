"""Map-tool outcomes in isolated Git fixtures; never import the trading app."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

TOOL = Path(__file__).resolve().parents[1] / "tools/codebase_map.py"
spec = importlib.util.spec_from_file_location("qtrades_code_map", TOOL)
assert spec and spec.loader
code_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(code_map)


class CodeMapTests(unittest.TestCase):
    def setUp(self) -> None:
        base = os.environ.get("QTRADES_MAP_TEST_TEMP")
        self.temp = tempfile.TemporaryDirectory(prefix="qtrades-map-", dir=base)
        self.root = Path(self.temp.name)
        self.write(
            "src/trading/engine.py",
            "raise AssertionError('Application import forbidden')\n"
            "class Engine:\n    def tick(self):\n        pass\n",
        )
        self.write(
            "src/trading/api.py",
            "from trading.engine import Engine\ndef create_app():\n"
            "    @app.get('/api/health')\n    def health():\n        return {}\n",
        )
        self.write("apps/web/src/App.tsx", "export function App() { return 'Unique map anchor' }\n")
        self.write("src/trading/idle.py", "def idle():\n    pass\n")
        self.write("requirements-lock.txt", "fixture-only\n")
        self.write(".gitignore", "data/\n")
        self.write("data/private.json", '{"must_not_read":true}\n')
        self.write(
            "docs/codebase-map/workflow.md",
            "# Workflow\n\n## Journey\n\nRead [engine](source-index.md#fixture-engine).\n"
            "\n## Another trace\n\nRead [UI](source-index.md#fixture-ui).\n",
        )
        self.write("docs/codebase-map/README.md", "# Map\n\n[Workflow](workflow.md#journey)\n")
        self.part: dict[str, Any] = {
            "references": [
                {
                    "id": "fixture-engine",
                    "path": "src/trading/engine.py",
                    "symbol": "Engine.tick",
                    "description": "Engine step",
                },
                {
                    "id": "fixture-health",
                    "path": "src/trading/api.py",
                    "symbol": "create_app.health",
                    "description": "Nested route",
                },
                {
                    "id": "fixture-ui",
                    "path": "apps/web/src/App.tsx",
                    "anchor": "Unique map anchor",
                    "description": "UI entry",
                },
            ],
            "tasks": [
                {
                    "id": "fixture-journey",
                    "title": "Trace fixture",
                    "guide": "workflow.md",
                    "section": "journey",
                    "references": ["fixture-engine", "fixture-health"],
                    "symptoms": ["tick missing"],
                }
            ],
        }
        self.write_part()
        self.areas = [
            {
                "id": "fixture",
                "guide": "workflow.md",
                "paths": [
                    "src/trading/engine.py",
                    "src/trading/api.py",
                    "src/trading/idle.py",
                    "apps/web/src/App.tsx",
                    "requirements-lock.txt",
                    ".gitignore",
                ],
            }
        ]
        self.write_areas()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Q-Trades disposable map fixture")
        self.git("config", "user.email", "qtrades-map@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Disposable source fixture")
        self.baseline = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.run_tool("--refresh", "--baseline", self.baseline)[0], 0)

    def tearDown(self) -> None:
        # This unique disposable directory is the complete intended target.
        assert self.root.resolve() == Path(self.temp.name).resolve()
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], stderr=subprocess.PIPE
        ).decode()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")

    def write_part(self) -> None:
        self.write("docs/codebase-map/parts/fixture.json", json.dumps(self.part))

    def write_areas(self) -> None:
        self.write("docs/codebase-map/areas.json", json.dumps(self.areas))

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = code_map.main(["--root", str(self.root), *args])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_complete_navigation_and_read_only_queries(self) -> None:
        before = self.git("status", "--porcelain")
        snapshot = (self.root / code_map.SNAPSHOT).read_bytes()
        index = (self.root / code_map.INDEX).read_text(encoding="utf-8")
        self.assertFalse(index.endswith("\n\n"))
        for args in (
            ("--check",),
            ("--tasks",),
            ("--lookup", "Engine.tick"),
            ("--task", "fixture-journey"),
            ("--trace", "workflow.md#another-trace"),
            ("--inventory",),
            ("--routes",),
            ("--dependencies", "src/trading/engine.py"),
        ):
            status, stdout, stderr = self.run_tool(*args)
            self.assertEqual(status, 0, stderr)
            self.assertTrue(stdout)
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual((self.root / code_map.SNAPSHOT).read_bytes(), snapshot)
        inventory = json.loads(self.run_tool("--inventory", "--json")[1])
        self.assertEqual(len(inventory), 6)
        self.assertNotIn("data/private.json", {item["path"] for item in inventory})

    def test_routes_nested_symbols_and_declared_consumers(self) -> None:
        routes = json.loads(self.run_tool("--routes", "--json")[1])
        self.assertEqual(
            [(r["method"], r["route"], r["handler"]) for r in routes],
            [("GET", "/api/health", "health")],
        )
        deps = json.loads(self.run_tool("--dependencies", "src/trading/engine.py", "--json")[1])
        self.assertEqual(deps["declared_consumers"], ["src/trading/api.py"])
        trace = json.loads(self.run_tool("--task", "fixture-journey", "--json")[1])
        self.assertEqual(
            {ref["id"] for ref in trace["references"]}, {"fixture-engine", "fixture-health"}
        )

    def test_new_consumer_or_route_in_unmatched_file_cannot_be_silently_omitted(self) -> None:
        self.write(
            "src/trading/idle.py",
            "from trading.engine import Engine\n@app.get('/new')\n"
            "def new_route():\n    return {}\n",
        )
        for args in (
            ("--dependencies", "src/trading/engine.py"),
            ("--lookup", "new_route"),
            ("--routes",),
        ):
            result = self.run_tool(*args)
            self.assertEqual(result[0], 1)
            self.assertIn("Snapshot-wide query is stale", result[2])
        self.assertEqual(self.run_tool("--task", "fixture-journey")[0], 0)

    def test_literal_lazy_side_effect_and_commonjs_imports_are_indexed(self) -> None:
        declared = code_map.imports(
            "App.tsx",
            "import './theme.css'; const lazy = import('./Lazy'); "
            "import {Foo} from './Foo'; const other = require('./old');",
        )
        self.assertEqual(declared, ["./Foo", "./Lazy", "./old", "./theme.css"])

    def test_changed_guide_text_cannot_mix_with_old_reference_export(self) -> None:
        with (self.root / "docs/codebase-map/workflow.md").open("a") as stream:
            stream.write("\nNew unreviewed recovery behavior\n")
        result = self.run_tool("--task", "fixture-journey")
        self.assertEqual(result[0], 1)
        self.assertIn("Stale selected guide", result[2])

    def test_trace_checks_linked_refs_even_without_named_task(self) -> None:
        trace = json.loads(self.run_tool("--trace", "workflow.md#another-trace", "--json")[1])
        self.assertEqual([ref["id"] for ref in trace["references"]], ["fixture-ui"])
        self.write("apps/web/src/App.tsx", "export function App() { return 'changed' }\n")
        result = self.run_tool("--trace", "workflow.md#another-trace")
        self.assertEqual(result[0], 1)
        self.assertIn("Stale selected source", result[2])

    def test_task_and_trace_accept_generated_index_headings_as_navigation(self) -> None:
        guide = self.root / "docs/codebase-map/workflow.md"
        guide.write_text(
            guide.read_text(encoding="utf-8").replace(
                "Read [engine]",
                "See [inventory](source-index.md#complete-tracked-inventory).\n\nRead [engine]",
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.run_tool("--refresh", "--baseline", self.baseline)[0], 0)
        for args in (("--task", "fixture-journey"), ("--trace", "workflow.md#journey")):
            status, stdout, stderr = self.run_tool(*args, "--json")
            self.assertEqual(status, 0, stderr)
            result = json.loads(stdout)
            self.assertEqual(
                {ref["id"] for ref in result["references"]},
                {"fixture-engine", "fixture-health"},
            )
            self.assertIn("source-index.md#complete-tracked-inventory", result["text"])
        saved = json.loads((self.root / code_map.SNAPSHOT).read_text(encoding="utf-8"))
        with self.assertRaisesRegex(code_map.MapError, "Unknown source-index fragments"):
            code_map.linked_source_refs(saved, "[missing](source-index.md#fixture-engin)")

    def test_changed_source_stays_visible_and_not_auto_accepted(self) -> None:
        snapshot = (self.root / code_map.SNAPSHOT).read_bytes()
        with (self.root / "src/trading/engine.py").open("a") as stream:
            stream.write("# changed behavior explanation\n")
        result = self.run_tool("--check")
        self.assertEqual(result[0], 1)
        self.assertIn("CHANGED src/trading/engine.py", result[1])
        self.assertEqual(self.run_tool("--task", "fixture-journey")[0], 1)
        self.assertEqual(self.run_tool("--lookup", "Engine.tick")[0], 1)
        self.assertEqual(self.run_tool("--dependencies", "src/trading/engine.py")[0], 1)
        self.assertEqual((self.root / code_map.SNAPSHOT).read_bytes(), snapshot)

    def test_checkout_newlines_do_not_create_false_drift(self) -> None:
        path = self.root / "src/trading/engine.py"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.run_tool("--check")[0], 0)

    def test_new_tracked_source_requires_explicit_inventory_owner(self) -> None:
        self.write("src/trading/new_owner.py", "def work():\n    pass\n")
        self.git("add", "src/trading/new_owner.py")
        result = self.run_tool("--check")
        self.assertEqual(result[0], 1)
        self.assertIn("ADDED src/trading/new_owner.py", result[1])
        self.assertIn("Expected one inventory area", result[1])

    def test_removed_inventory_and_missing_anchor_refuse(self) -> None:
        self.git("rm", "--cached", "src/trading/engine.py")
        result = self.run_tool("--check")
        self.assertEqual(result[0], 1)
        self.assertIn("REMOVED src/trading/engine.py", result[1])

    def test_duplicate_symbol_and_literal_are_not_silently_selected(self) -> None:
        self.write(
            "src/trading/engine.py",
            "class Engine:\n    def tick(self):\n        pass\n    def tick(self):\n        pass\n",
        )
        result = self.run_tool("--check")
        self.assertEqual(result[0], 1)
        self.assertIn("found 2", result[1])
        self.write("src/trading/engine.py", "class Engine:\n    def tick(self):\n        pass\n")
        self.write("apps/web/src/App.tsx", "Unique map anchor\nUnique map anchor\n")
        self.assertIn("ambiguous literal", self.run_tool("--check")[1])

    def test_unknown_task_reference_and_missing_heading_refuse(self) -> None:
        self.part["tasks"][0]["references"].append("missing-owner")
        self.write_part()
        self.assertIn("Unknown task references", self.run_tool("--check")[1])
        self.part["tasks"][0]["references"].pop()
        self.part["tasks"][0]["section"] = "missing-heading"
        self.write_part()
        self.assertIn("Missing task section", self.run_tool("--check")[1])

    def test_broken_links_and_generated_index_edit_refuse(self) -> None:
        self.write(
            "docs/codebase-map/README.md", "# Map\n\n[missing](workflow.md#does-not-exist)\n"
        )
        self.assertIn("missing fragment", self.run_tool("--check")[1])
        self.write("docs/codebase-map/README.md", "# Map\n")
        with (self.root / code_map.INDEX).open("a") as stream:
            stream.write("Edited generated result\n")
        self.assertIn("Generated source index differs", self.run_tool("--check")[1])

    def test_duplicate_ids_and_unknown_queries_refuse(self) -> None:
        self.assertEqual(self.run_tool("--lookup", "does-not-exist")[0], 1)
        self.assertEqual(self.run_tool("--task", "does-not-exist")[0], 1)
        self.part["references"].append(dict(self.part["references"][0]))
        self.write_part()
        result = self.run_tool("--check")
        self.assertEqual(result[0], 1)
        self.assertIn("Duplicate reference IDs", result[1] + result[2])

    def test_reference_path_and_trace_escape_refuse(self) -> None:
        with self.assertRaises(code_map.MapError):
            code_map.local(self.root, "../private.py")
        self.assertEqual(self.run_tool("--trace", "../../../private.md")[0], 1)

    @unittest.skipIf(
        os.name == "nt", "Real symlink fixture requires Unix or Windows symlink privilege"
    )
    def test_symlinked_guide_outside_repository_is_never_read(self) -> None:
        outside = self.root.parent / (self.root.name + "-outside-guide.md")
        self.assertTrue(outside.resolve().is_relative_to(self.root.parent.resolve()))
        outside.write_text("PRIVATE SOURCE MUST NOT BE READ\n", encoding="utf-8")
        try:
            guide = self.root / "docs/codebase-map/README.md"
            guide.unlink()
            guide.symlink_to(outside)
            result = self.run_tool("--refresh", "--baseline", self.baseline)
            self.assertEqual(result[0], 1)
            self.assertIn("Path escapes repository", result[2])
            self.assertNotIn("PRIVATE SOURCE", result[1] + result[2])
        finally:
            outside.unlink()

    def test_failed_refresh_retains_original_outputs_and_line_links_are_checked(self) -> None:
        old_snapshot = (self.root / code_map.SNAPSHOT).read_bytes()
        old_index = (self.root / code_map.INDEX).read_bytes()
        self.write(
            "docs/codebase-map/README.md",
            "# Map\n\n[bad line](../../src/trading/engine.py#L900)\n",
        )
        result = self.run_tool("--refresh", "--baseline", self.baseline)
        self.assertEqual(result[0], 1)
        self.assertIn("missing source line", result[2])
        self.assertEqual((self.root / code_map.SNAPSHOT).read_bytes(), old_snapshot)
        self.assertEqual((self.root / code_map.INDEX).read_bytes(), old_index)

    def test_area_conflict_and_changed_task_metadata_refuse(self) -> None:
        self.areas.append(dict(self.areas[0]))
        self.write_areas()
        self.assertIn("Expected one inventory area", self.run_tool("--check")[1])
        self.areas.pop()
        self.write_areas()
        self.part["tasks"][0]["title"] = "Changed task meaning"
        self.write_part()
        self.assertIn("Map metadata", self.run_tool("--check")[1])
        self.assertIn("metadata changed", self.run_tool("--tasks")[2])
        self.assertEqual(self.run_tool("--lookup", "Engine.tick")[0], 1)


if __name__ == "__main__":
    unittest.main()
