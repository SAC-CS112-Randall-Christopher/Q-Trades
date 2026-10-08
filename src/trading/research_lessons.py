"""Referenced, append-only interpretations in the existing research registry.

Financial results stay with the sole writer. Viewing a lesson records disclosure,
never an observation, vote or training weight. Selection has no risk authority.
"""

import json
import time
from contextlib import nullcontext
from typing import Any

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.role_evidence import strategy_summary


class ResearchLessons:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS research_lessons(
                    seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, task TEXT UNIQUE NOT NULL,
                    family TEXT NOT NULL, parent TEXT, horizon TEXT NOT NULL, outcome TEXT NOT NULL,
                    cost_sha TEXT NOT NULL, data_basis TEXT NOT NULL, mechanism TEXT NOT NULL,
                    body TEXT NOT NULL, sha TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS lesson_lookup
                    ON research_lessons(family,horizon,outcome,seq);
                CREATE TABLE IF NOT EXISTS lesson_access(
                    id TEXT PRIMARY KEY, reads INTEGER NOT NULL, last_read REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS lesson_notes(
                    seq INTEGER PRIMARY KEY, lesson TEXT NOT NULL, supersedes INTEGER,
                    note TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS research_selection(
                    lesson TEXT PRIMARY KEY, state TEXT NOT NULL, next_task TEXT,
                    reason TEXT NOT NULL, updated REAL NOT NULL, retry_at REAL NOT NULL DEFAULT 0);
                CREATE TRIGGER IF NOT EXISTS frozen_lesson_update BEFORE UPDATE ON research_lessons
                  BEGIN SELECT RAISE(ABORT,'Supported lesson is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS frozen_lesson_delete BEFORE DELETE ON research_lessons
                  BEGIN SELECT RAISE(ABORT,'Supported lesson is permanent'); END;
                CREATE TRIGGER IF NOT EXISTS frozen_note_update BEFORE UPDATE ON lesson_notes
                  BEGIN SELECT RAISE(ABORT,'Interpretations append or supersede'); END;
                CREATE TRIGGER IF NOT EXISTS frozen_note_delete BEFORE DELETE ON lesson_notes
                  BEGIN SELECT RAISE(ABORT,'Interpretations are permanent'); END;
            """)
            if "retry_at" not in {
                r["name"] for r in registry.db.execute("PRAGMA table_info(research_selection)")
            }:
                registry.db.execute(
                    "ALTER TABLE research_selection ADD COLUMN retry_at REAL NOT NULL DEFAULT 0"
                )

    def record(self, task: dict[str, Any]) -> str:
        result = task["result"]
        if not result or not result.get("outcome") or task["stage"] != "complete":
            raise ValueError("A lesson requires a completed task with a recorded mature outcome")
        source = result["outcome"]
        score = source["body"]
        proposal = task["proposal"]
        if not proposal or score["proposal_id"] != proposal["request_id"]:
            raise ValueError("Lesson source and frozen proposal differ")
        identity = "lesson-" + fingerprint({"task": task["id"], "source": source})[:32]
        followup = result.get("followup", {})
        body = {
            "version": "supported-lesson-v1",
            "id": identity,
            "task": task["id"],
            "claim": "Recorded " + score["outcome"] + ": " + score["reason"],
            "context": {
                "family": proposal["strategy"]["family"],
                "mechanism": proposal["mechanism"],
                "parent": proposal["parent_trial"],
                "horizon": proposal["strategy"]["holding_horizon"],
                "strategy": strategy_summary(proposal["strategy"]),
                "strategy_sha256": fingerprint(proposal["strategy"]),
                "reference": strategy_summary(proposal["reference"]),
                "reference_sha256": fingerprint(proposal["reference"]),
                "method_reference": {"task": task["id"], "field": "proposal"},
                "cost_policy": task["context"]["policy"],
                "data_basis": task["context"]["tool_evidence"]["source_basis"],
                "input_sha256": task["context"]["tool_evidence"]["closed_bar_sha256"],
            },
            "source": source,
            "source_sha256": fingerprint(source),
            "evaluation_reference": (task["evaluation"] or {}).get("detail_reference"),
            "support": {"recorded_comparisons": 1, "independent_samples": None},
            "supporting_facts": {
                k: score[k]
                for k in (
                    "net_after_operating_usd",
                    "delta_usd",
                    "passive_usd",
                    "cash_usd",
                    "operating_each_usd",
                    "fees_treatment",
                    "coverage_seconds",
                )
            },
            "contrary_facts": score["reason"],
            "cause": "data_incomplete" if score["outcome"] == "data_blocked" else "unresolved",
            "unknowns": [
                "Recognition, lateness, execution, exit and size causes require linked diagnostics",
                "Related windows are correlated; retrieval frequency is not statistical support",
                "No incumbent qualification or independent market benefit follows",
            ],
            "next_test": followup,
            "reconsideration": followup.get("dependency")
            or "A supported different capability or new mature/source evidence is required",
            "interpretation_scope": "Model rationale is annotation; exact metrics are tool-owned",
        }
        encoded = json.dumps(body, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 32768:
            raise ValueError("Lesson exceeds its bounded reference record")
        context = body["context"]
        with self.registry.transaction():
            self.registry.db.execute(
                "INSERT OR IGNORE INTO research_lessons "
                "(id,task,family,parent,horizon,outcome,cost_sha,data_basis,"
                "mechanism,body,sha,created) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    task["id"],
                    context["family"],
                    context["parent"],
                    context["horizon"],
                    score["outcome"],
                    fingerprint(context["cost_policy"]),
                    context["data_basis"],
                    context["mechanism"],
                    encoded,
                    fingerprint(body),
                    time.time(),
                ),
            )
            saved = self.registry.db.execute(
                "SELECT id,sha FROM research_lessons WHERE task=?", (task["id"],)
            ).fetchone()
            if saved["id"] != identity or saved["sha"] != fingerprint(body):
                raise ValueError("A completed lesson cannot change its supporting interpretation")
        return identity

    def _disclose(self, row: Any) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(row["body"])
        score = body["source"]["body"]
        if score["available_at"] > time.time():
            raise ValueError("Referenced outcome is not available at the current cutoff")
        # Standalone reads commit before return. Publication joins its existing
        # transaction so disclosure and the question become visible together.
        with self.registry.lock:
            transaction = (
                nullcontext() if self.registry.db.in_transaction else self.registry.transaction()
            )
            with transaction:
                self.registry.db.execute(
                    "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,'lesson disclosure')",
                    ("lesson:" + row["id"], score["window_start"], score["available_at"]),
                )
                self.registry.db.execute(
                    "INSERT INTO lesson_access VALUES(?,1,?) ON CONFLICT(id) DO UPDATE "
                    "SET reads=reads+1,last_read=excluded.last_read",
                    (row["id"], time.time()),
                )
                access = dict(
                    self.registry.db.execute(
                        "SELECT reads,last_read FROM lesson_access WHERE id=?", (row["id"],)
                    ).fetchone()
                )
                notes = [
                    dict(n)
                    for n in self.registry.db.execute(
                        "SELECT * FROM lesson_notes WHERE lesson=? ORDER BY seq DESC LIMIT 20",
                        (row["id"],),
                    )
                ]
                selection = self.registry.db.execute(
                    "SELECT * FROM research_selection WHERE lesson=?", (row["id"],)
                ).fetchone()
        return body | {
            "sha256": row["sha"],
            "access": access,
            "notes": notes,
            "selection": dict(selection) if selection else None,
        }

    def get(self, identity: str) -> dict[str, Any]:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM research_lessons WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise ValueError("Unknown supported lesson")
        return self._disclose(row)

    def retrieve(self, *, before: int = 0, text: str = "", **filters: str) -> dict[str, Any]:
        allowed = {"family", "parent", "horizon", "outcome", "cost_sha", "data_basis"}
        if not set(filters) <= allowed or len(text) > 200:
            raise ValueError("Unsupported lesson query")
        where = ["seq<?"]
        args: list[Any] = [before or 9223372036854775807]
        for key, value in filters.items():
            if value:
                where.append(key + "=?")
                args.append(value)
        if text:
            where.append("(instr(mechanism,?)>0 OR instr(body,?)>0)")
            args.extend([text, text])
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT * FROM research_lessons WHERE "
                + " AND ".join(where)
                + " ORDER BY seq DESC LIMIT 21",
                args,
            ).fetchall()
        items = []
        for row in rows[:20]:
            item = self._disclose(row)
            items.append(
                {
                    k: item[k]
                    for k in (
                        "id",
                        "claim",
                        "context",
                        "cause",
                        "support",
                        "sha256",
                        "selection",
                        "access",
                    )
                }
            )
        return {
            "lessons": items,
            "next_before": rows[19]["seq"] if len(rows) > 20 else None,
            "scope": "Referenced comparisons; failed and inconclusive cases included",
            "population": "Curated retrieval never replaces the original numerical population",
        }

    def annotate(self, identity: str, note: str, supersedes: int | None = None) -> int:
        if not 12 <= len(note) <= 1200:
            raise ValueError("Interpretation must be a bounded explanatory note")
        self.get(identity)
        with self.registry.transaction():
            if (
                supersedes is not None
                and not self.registry.db.execute(
                    "SELECT 1 FROM lesson_notes WHERE seq=? AND lesson=?", (supersedes, identity)
                ).fetchone()
            ):
                raise ValueError("Superseded note must belong to this lesson")
            cursor = self.registry.db.execute(
                "INSERT INTO lesson_notes(lesson,supersedes,note,created) VALUES(?,?,?,?)",
                (identity, supersedes, note, time.time()),
            )
            return int(cursor.lastrowid or 0)

    def selected(self, lesson: str, state: str, reason: str, next_task: str | None = None) -> None:
        with self.registry.lock:
            transaction = (
                nullcontext() if self.registry.db.in_transaction else self.registry.transaction()
            )
            with transaction:
                self.registry.db.execute(
                    "INSERT INTO research_selection VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(lesson) DO UPDATE "
                    "SET state=excluded.state,next_task=excluded.next_task,reason=excluded.reason,"
                    "retry_at=excluded.retry_at,updated=CASE WHEN state<>excluded.state OR "
                    "reason<>excluded.reason OR next_task IS NOT excluded.next_task "
                    "THEN excluded.updated ELSE updated END "
                    "WHERE state<>excluded.state OR reason<>excluded.reason "
                    "OR next_task IS NOT excluded.next_task OR state='deferred'",
                    (
                        lesson,
                        state,
                        next_task,
                        reason,
                        time.time(),
                        time.time() + 60 if state == "deferred" else 0,
                    ),
                )
