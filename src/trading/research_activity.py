"""Bounded read-only activity dates; polling time never substitutes for evidence time."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from trading.outcome_continuation import NAME
from trading.research_storage import compact_path, storage_snapshot


def sqlite_rows(path: Path, query: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return [dict(r) for r in db.execute(query)]


class ResearchActivity:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = Lock()
        self.cached: dict[str, Any] | None = None
        self.cached_at = 0.0

    def snapshot(self, dsn: str | None, runtime: Any, lab: Any) -> dict[str, Any]:
        with self.lock:
            if self.cached is not None and time.monotonic() - self.cached_at < 10:
                return self.cached
            result: dict[str, Any] = {
                "queried_at": time.time(),
                "market": None,
                "candle": None,
                "processing": None,
                "signal": None,
                "scheduled_review": None,
                "full_evidence": None,
                "training_input": None,
                "mature_outcome": None,
                "available_outcome": None,
                "completed_learning": None,
                "jobs": [],
                "campaigns": [],
                "warnings": [],
                "next_action": "Paper/research service unavailable",
                "meaning": (
                    "Activity times come from observations and immutable receipts; "
                    "saved model trials have their own historical dates"
                ),
            }
            if runtime:
                result["processing"] = runtime.state.get("last_tick")
                result["resource_reason"] = (
                    "Optional research yielding to financial processing/resource guard"
                    if getattr(runtime, "constrained", lambda: False)()
                    else None
                )
            if dsn:
                try:
                    options = str(conninfo_to_dict(dsn).get("options") or "")
                    readonly = make_conninfo(
                        dsn,
                        options=options
                        + " -c default_transaction_read_only=on -c statement_timeout=1500",
                    )
                    with psycopg.connect(readonly, row_factory=dict_row) as db:
                        for key, kind in (
                            ("market", "market_minute"),
                            ("signal", "decision"),
                            ("scheduled_review", "scheduled_review"),
                        ):
                            row = db.execute(
                                (
                                    "SELECT id,at FROM paper_events WHERE kind=%s ORDER BY id DESC "
                                    "LIMIT 1"
                                ),
                                (kind,),
                            ).fetchone()
                            result[key] = dict(row) if row else None
                        row = db.execute(
                            "SELECT open_ms,observed_at FROM paper_bars WHERE "
                            "symbol='BTCUSD' ORDER BY open_ms DESC LIMIT 1"
                        ).fetchone()
                        result["candle"] = dict(row) if row else None
                except psycopg.Error:
                    result["warnings"].append("Durable financial activity query unavailable")
            meta: list[dict[str, Any]] = []
            try:
                root = self.directory
                result["storage"] = storage_snapshot(root)
                memory = compact_path(root)
                full = sqlite_rows(
                    root / "research-evidence.sqlite",
                    "SELECT id,at,kind FROM evidence_records ORDER BY id DESC LIMIT 1",
                )
                meta = sqlite_rows(
                    root / "research-evidence.sqlite",
                    "SELECT state,bytes,rows FROM evidence_meta WHERE id=1",
                )
                result["full_evidence"] = {
                    "latest": full[0] if full else None,
                    "capacity": meta[0] if meta else None,
                }
                prefixes = sqlite_rows(
                    memory,
                    (
                        "SELECT seq,episode,available,cutoff,sha256 FROM "
                        "compact_prefixes ORDER BY seq DESC LIMIT 1"
                    ),
                )
                result["training_input"] = prefixes[0] if prefixes else None
                for key, clause in (
                    ("mature_outcome", ""),
                    ("available_outcome", "WHERE json_extract(body,'$.status')='available'"),
                ):
                    labels = sqlite_rows(
                        memory,
                        (
                            "SELECT episode,available,json_extract(body,'$.status') AS "
                            "status FROM compact_outcomes "
                        )
                        + clause
                        + " ORDER BY available DESC LIMIT 1",
                    )
                    result[key] = labels[0] if labels else None
                    continued = sqlite_rows(
                        memory.parent / NAME,
                        "SELECT episode,available,json_extract(body,'$.status') AS status "
                        "FROM continued_outcomes WHERE source='compact' "
                        + ("AND json_extract(body,'$.status')='available' " if clause else "")
                        + "ORDER BY available DESC LIMIT 1",
                    )
                    if continued and (
                        result[key] is None or continued[0]["available"] > result[key]["available"]
                    ):
                        result[key] = continued[0]
                result["maturity"] = getattr(
                    getattr(runtime, "evidence", None), "maturity_status", None
                )
                if result["maturity"] is None:
                    result["maturity"] = result["storage"].get("maturity")
                result["jobs"] = sqlite_rows(
                    root / "experiments.sqlite3",
                    "SELECT status,count(*) AS count FROM experiments GROUP BY status",
                )
                result["campaigns"] = sqlite_rows(
                    root / "experiments.sqlite3",
                    (
                        "SELECT request_id,status,reason,phase,last_dispatch FROM "
                        "research_campaigns ORDER BY seq DESC LIMIT 4"
                    ),
                )
                learned = sqlite_rows(
                    root / "experiments.sqlite3",
                    (
                        "SELECT seq,request_id,at,kind FROM learning_stages WHERE kind "
                        "IN ('score','update') ORDER BY seq DESC LIMIT 1"
                    ),
                )
                completed = sqlite_rows(
                    root / "experiments.sqlite3",
                    (
                        "SELECT request_id,finished,status FROM experiments WHERE "
                        "status='completed' ORDER BY seq DESC LIMIT 1"
                    ),
                )
                result["completed_learning"] = (
                    learned[0] if learned else completed[0] if completed else None
                )
            except (sqlite3.Error, OSError):
                result["warnings"].append("Some retained research activity queries are unavailable")
            active = any(
                r["status"] in {"waiting_inputs", "queued", "running"} and r["count"] > 0
                for r in result["jobs"]
            )
            campaigns = any(r["status"] == "active" for r in result["campaigns"])
            result["next_action"] = (
                "Research worker unavailable"
                if lab is None
                else "Research queued; "
                + (result.get("resource_reason") or "waiting for bounded worker dispatch")
                if active
                else "Finite campaign waiting: " + str(lab.blocked_reason or "next eligible inputs")
                if campaigns
                else (
                    "No active research job or campaign. Start a declared policy; "
                    "saved model-evaluation files do not schedule learning."
                )
            )
            continuous = runtime.state.get("autonomous_lab") if runtime else None
            if continuous:
                result["next_action"] = continuous["phase"] + ": " + continuous["reason"]
                result["next_action_at"] = continuous["next_action_at"]
                if continuous["last_score_at"] is not None:
                    result["completed_learning"] = {
                        "at": continuous["last_score_at"],
                        "kind": "lab_trial_scored",
                    }
            external = result.get("storage", {})
            if external.get("last_capture") is not None:
                result["full_evidence"] = {
                    "latest": {"at": external["last_capture"]},
                    "capacity": {"state": external["state"]},
                }
            if meta and meta[0]["state"] == "capacity" and external.get("state") != "recording":
                result["warnings"].append(
                    "Full replay evidence archive is at its declared physical "
                    "capacity; compact inputs and financial collection are separate"
                )
            self.cached, self.cached_at = result, time.monotonic()
            return result
