"""Verified role-payload continuation in the existing G: research tiers."""

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, closing, contextmanager
from typing import Any

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.research_storage import ResearchStorage, StoragePlan, load_plan

HOT_TASKS = 512
WRITE_HEADROOM = 256 * 1024
ROLLOVER_BYTES = 384 * 1024**2


class HistoryUnavailable(ValueError):
    """Recoverable storage admission failure; original records remain authoritative."""


class RoleHistory:
    def __init__(
        self,
        registry: ExperimentRegistry,
        storage_owner: Callable[[StoragePlan], AbstractContextManager[ResearchStorage]]
        | None = None,
    ):
        self.registry = registry
        self.storage_owner = storage_owner
        with registry.transaction():
            columns = {r[1] for r in registry.db.execute("PRAGMA table_info(role_tasks)")}
            for name in ("archive_reference", "archive_sha256", "question_text"):
                if name not in columns:
                    registry.db.execute(f"ALTER TABLE role_tasks ADD COLUMN {name} TEXT")
            registry.db.execute(
                "UPDATE role_tasks SET question_text=json_extract(context,'$.question.question') "
                "WHERE question_text IS NULL"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_active ON role_tasks(updated) "
                "WHERE status NOT IN ('done','failed')"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_history_created "
                "ON role_tasks(created DESC,id DESC)"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_hot ON role_tasks(created) "
                "WHERE archive_reference IS NULL"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_attempt_started ON role_attempts(started)"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_unreturned_attempt ON role_attempts(task) "
                "WHERE finished IS NULL AND response IS NULL"
            )
            registry.db.execute(
                "CREATE TABLE IF NOT EXISTS role_followups(task TEXT PRIMARY KEY,"
                "state TEXT NOT NULL DEFAULT 'pending',retry_at REAL NOT NULL DEFAULT 0)"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_followup_due ON role_followups(retry_at,task) "
                "WHERE state='pending'"
            )
            for event in ("INSERT", "UPDATE OF stage,status,result"):
                name = "role_followup_insert" if event == "INSERT" else "role_followup_update"
                registry.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {event} ON role_tasks "
                    "WHEN NEW.stage='complete' AND NEW.status='done' "
                    "AND json_extract(NEW.result,'$.outcome') IS NOT NULL "
                    "BEGIN INSERT OR IGNORE INTO role_followups(task) VALUES(NEW.id); END"
                )
            registry.db.execute(
                "CREATE TABLE IF NOT EXISTS role_followup_backfill(id INTEGER PRIMARY KEY,"
                "through INTEGER NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,"
                "retry_at REAL NOT NULL DEFAULT 0,reason TEXT)"
            )
            registry.db.execute(
                "INSERT OR IGNORE INTO role_followup_backfill(id,through) "
                "SELECT 1,coalesce(max(rowid),0) FROM role_tasks"
            )
            registry.db.execute(
                "CREATE TABLE IF NOT EXISTS role_archive_attempts("
                "task TEXT NOT NULL,stage TEXT NOT NULL,attempt INTEGER NOT NULL,"
                "started REAL NOT NULL,wall_reserved REAL NOT NULL,"
                "tokens_reserved INTEGER NOT NULL,"
                "actor TEXT,PRIMARY KEY(task,stage,attempt))"
            )
            registry.db.execute(
                "CREATE INDEX IF NOT EXISTS role_archive_started ON role_archive_attempts(started)"
            )
            archived_columns = {
                r[1] for r in registry.db.execute("PRAGMA table_info(role_archive_attempts)")
            }
            for name, kind in (
                ("status", "TEXT"),
                ("input_tokens", "INTEGER"),
                ("output_tokens", "INTEGER"),
                ("measured_wall_seconds", "REAL"),
            ):
                if name not in archived_columns:
                    registry.db.execute(
                        f"ALTER TABLE role_archive_attempts ADD COLUMN {name} {kind}"
                    )
            registry.db.execute(
                "CREATE VIEW IF NOT EXISTS role_attempt_allowances AS "
                "SELECT task,stage,attempt,started,wall_reserved,tokens_reserved,"
                "json_extract(profile,'$.actor') AS actor FROM role_attempts UNION ALL "
                "SELECT task,stage,attempt,started,wall_reserved,tokens_reserved,actor "
                "FROM role_archive_attempts"
            )
            registry.db.execute(
                "CREATE VIEW IF NOT EXISTS role_attempt_usage AS "
                "SELECT task,stage,attempt,started,status,json_extract(profile,'$.actor') AS actor,"
                "json_extract(response,'$.tokens.prompt_eval_count') AS input_tokens,"
                "json_extract(response,'$.tokens.eval_count') AS output_tokens,"
                "json_extract(response,'$.wall_seconds') AS measured_wall_seconds "
                "FROM role_attempts UNION ALL SELECT task,stage,attempt,started,status,actor,"
                "input_tokens,output_tokens,measured_wall_seconds FROM role_archive_attempts"
            )
            search_exists = registry.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='role_task_search'"
            ).fetchone()
            registry.db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS role_task_search USING "
                "fts5(question_text,content='role_tasks',content_rowid='rowid')"
            )
            if not search_exists:
                # Migration from the old, at-most-512-task registry; never repeat on restart.
                registry.db.execute(
                    "INSERT INTO role_task_search(role_task_search) VALUES('rebuild')"
                )
            registry.db.execute(
                "CREATE TRIGGER IF NOT EXISTS role_search_insert AFTER INSERT ON role_tasks "
                "BEGIN UPDATE role_tasks SET "
                "question_text=json_extract(context,'$.question.question') "
                "WHERE rowid=NEW.rowid AND question_text IS NULL; "
                "INSERT INTO role_task_search(rowid,question_text) VALUES(NEW.rowid,"
                "coalesce(NEW.question_text,json_extract(NEW.context,'$.question.question'))); END"
            )

    @contextmanager
    def storage(self) -> Iterator[ResearchStorage]:
        plan = load_plan(self.registry.path.parent)
        if plan is None:
            raise HistoryUnavailable(
                "Role history continuation requires the configured G: research tiers"
            )
        access = (
            self.storage_owner(plan)
            if self.storage_owner is not None
            else closing(ResearchStorage(plan))
        )
        with access as store:
            yield store

    def _snapshot(self, row: sqlite3.Row) -> dict[str, Any]:
        attempts = self.registry.db.execute(
            "SELECT * FROM role_attempts WHERE task=? ORDER BY started,rowid", (row["id"],)
        ).fetchall()
        return {"record": dict(row), "attempts": [dict(a) for a in attempts]}

    def _usage(self) -> tuple[int, int]:
        size = self.registry.db.execute("PRAGMA page_size").fetchone()[0]
        pages = self.registry.db.execute("PRAGMA page_count").fetchone()[0]
        free = self.registry.db.execute("PRAGMA freelist_count").fetchone()[0]
        maximum = self.registry.db.execute("PRAGMA max_page_count").fetchone()[0]
        used = (pages - free) * size
        return used, maximum * size - used

    def rollover(self) -> None:
        """At most eight terminal payloads; exact cold commit precedes hot replacement."""
        with self.registry.lock:
            hot = self.registry.db.execute(
                "SELECT count(*) FROM role_tasks WHERE archive_reference IS NULL"
            ).fetchone()[0]
            used, headroom = self._usage()
            if hot < HOT_TASKS and used < ROLLOVER_BYTES and headroom >= WRITE_HEADROOM:
                return
            rows = self.registry.db.execute(
                "SELECT * FROM role_tasks WHERE archive_reference IS NULL AND "
                "status IN ('done','failed') AND owner IS NULL AND lease_until IS NULL "
                "AND NOT EXISTS(SELECT 1 FROM role_attempts a WHERE a.task=role_tasks.id "
                "AND a.finished IS NULL AND a.response IS NULL) "
                "ORDER BY created,id LIMIT 8"
            ).fetchall()
            if rows:
                try:
                    with self.storage() as store:
                        for row in rows:
                            saved = self._snapshot(row)
                            packet = {"kind": "role_task_history_v1", "at": time.time(), **saved}
                            reference = store.append([packet], time.time())[0]
                            if store.reopen(reference) != packet:
                                raise ValueError(
                                    "Role history archive verification failed; hot work retained"
                                )
                            with self.registry.transaction():
                                current = self.registry.db.execute(
                                    "SELECT * FROM role_tasks WHERE id=?", (row["id"],)
                                ).fetchone()
                                if current is None or self._snapshot(current) != saved:
                                    continue  # Another owner progressed; preserve its hot record.
                                context = json.loads(row["context"])
                                self.registry.db.execute(
                                    "UPDATE role_tasks SET context=?,proposal=NULL,evaluation=NULL,"
                                    "result=NULL,archive_reference=?,archive_sha256=? WHERE id=?",
                                    (
                                        json.dumps(
                                            {"question": context["question"]}
                                            | (
                                                {"contract": context["contract"]}
                                                if "contract" in context
                                                else {}
                                            )
                                            | (
                                                {
                                                    key: context[key]
                                                    for key in (
                                                        "policy_sha256",
                                                        "question_selection",
                                                        "selection_authority",
                                                    )
                                                    if key in context
                                                }
                                            )
                                            | (
                                                {
                                                    key: context[key]
                                                    for key in ("execution_mode", "pilot_grant_id")
                                                    if key in context
                                                }
                                                if "execution_mode" in context
                                                else {}
                                            )
                                        ),
                                        reference,
                                        fingerprint(packet),
                                        row["id"],
                                    ),
                                )
                                self.registry.db.execute(
                                    "DELETE FROM role_attempts WHERE task=?", (row["id"],)
                                )
                                for attempt in saved["attempts"]:
                                    response = (
                                        json.loads(attempt["response"])
                                        if attempt["response"]
                                        else {}
                                    )
                                    tokens = response.get("tokens") or {}
                                    self.registry.db.execute(
                                        "INSERT INTO role_archive_attempts"
                                        "(task,stage,attempt,started,"
                                        "wall_reserved,tokens_reserved,actor,status,input_tokens,"
                                        "output_tokens,measured_wall_seconds) "
                                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                        (
                                            row["id"],
                                            attempt["stage"],
                                            attempt["attempt"],
                                            attempt["started"],
                                            attempt["wall_reserved"],
                                            attempt["tokens_reserved"],
                                            json.loads(attempt["profile"]).get("actor"),
                                            attempt["status"],
                                            tokens.get("prompt_eval_count"),
                                            tokens.get("eval_count"),
                                            response.get("wall_seconds"),
                                        ),
                                    )
                except (sqlite3.Error, OSError, LookupError) as exc:
                    raise HistoryUnavailable(
                        "Role history continuation unavailable; original work retained"
                    ) from exc
            if (
                self.registry.db.execute(
                    "SELECT count(*) FROM role_tasks WHERE archive_reference IS NULL"
                ).fetchone()[0]
                >= HOT_TASKS
            ):
                raise HistoryUnavailable(
                    "Role history continuation awaits verified storage or terminal work"
                )
            if self._usage()[1] < WRITE_HEADROOM:
                raise HistoryUnavailable(
                    "Role history lacks physical write headroom; retained history is intact. "
                    "Restore space in the declared tiers before retrying."
                )

    def read(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            with self.storage() as store:
                packet = store.reopen(row["archive_reference"])
        except (OSError, LookupError, sqlite3.Error) as exc:
            raise HistoryUnavailable(
                "Saved role history unavailable; no replacement inferred"
            ) from exc
        if fingerprint(packet) != row["archive_sha256"] or packet["kind"] != "role_task_history_v1":
            raise ValueError("Saved role history hash differs")
        saved = packet["record"]
        if any(saved[key] != row[key] for key in ("id", "created", "updated", "stage", "status")):
            raise ValueError("Saved role history metadata differs")
        return {
            **saved,
            "attempts": packet["attempts"],
            "archive_reference": row["archive_reference"],
            "archive_sha256": row["archive_sha256"],
        }

    def discover_followups(self, now: float | None = None) -> int:
        """One-time legacy discovery, at most eight records; never rescan cold history."""
        now = time.time() if now is None else now
        with self.registry.lock:
            progress = self.registry.db.execute(
                "SELECT * FROM role_followup_backfill WHERE id=1"
            ).fetchone()
            if progress["retry_at"] > now or progress["cursor"] >= progress["through"]:
                return 0
            rows = self.registry.db.execute(
                "SELECT rowid AS migration_row,* FROM role_tasks "
                "WHERE rowid>? AND rowid<=? ORDER BY rowid LIMIT 8",
                (progress["cursor"], progress["through"]),
            ).fetchall()
            found = 0
            for row in rows:
                state = "pending"
                eligible = row["stage"] == "complete" and row["status"] == "done"
                try:
                    saved = self.read(row) if eligible and row["archive_reference"] else dict(row)
                except HistoryUnavailable as exc:
                    with self.registry.transaction():
                        self.registry.db.execute(
                            "UPDATE role_followup_backfill SET retry_at=?,reason=? WHERE id=1",
                            (now + 30, str(exc)[:500]),
                        )
                    raise
                result = json.loads(saved["result"]) if eligible and saved["result"] else {}
                eligible = eligible and bool(result.get("outcome"))
                with self.registry.transaction():
                    if eligible:
                        if (
                            self.registry.db.execute(
                                "SELECT 1 FROM sqlite_master WHERE name='research_selection'"
                            ).fetchone()
                            and self.registry.db.execute(
                                "SELECT 1 FROM research_selection s JOIN research_lessons l "
                                "ON l.id=s.lesson WHERE l.task=? "
                                "AND s.state IN ('selected','waiting')",
                                (row["id"],),
                            ).fetchone()
                        ):
                            state = "consumed"
                        found += self.registry.db.execute(
                            "INSERT OR IGNORE INTO role_followups(task,state) VALUES(?,?)",
                            (row["id"], state),
                        ).rowcount
                    self.registry.db.execute(
                        "UPDATE role_followup_backfill SET cursor=?,retry_at=0,reason=NULL "
                        "WHERE id=1",
                        (row["migration_row"],),
                    )
            return found

    def restore(self, identity: str) -> None:
        """Explicit operational retry restores the same answers and charged attempts."""
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM role_tasks WHERE id=?", (identity,)
            ).fetchone()
            if not row or row["archive_reference"] is None:
                return
            saved = self.read(row)
            self.rollover()
            with self.registry.transaction():
                if not self.registry.db.execute(
                    "UPDATE role_tasks SET context=?,proposal=?,evaluation=?,result=?,"
                    "archive_reference=NULL,archive_sha256=NULL WHERE id=? AND archive_reference=?",
                    (
                        saved["context"],
                        saved["proposal"],
                        saved["evaluation"],
                        saved["result"],
                        identity,
                        row["archive_reference"],
                    ),
                ).rowcount:
                    raise ValueError("Role history ownership changed; inspect the retained task")
                for attempt in saved["attempts"]:
                    keys = list(attempt)
                    self.registry.db.execute(
                        "INSERT INTO role_attempts("
                        + ",".join(keys)
                        + ") VALUES("
                        + ",".join("?" for _ in keys)
                        + ")",
                        list(attempt.values()),
                    )
                self.registry.db.execute(
                    "DELETE FROM role_archive_attempts WHERE task=?", (identity,)
                )
