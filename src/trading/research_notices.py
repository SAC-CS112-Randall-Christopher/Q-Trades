"""Small operational projection in the existing registry; no research dispatch authority."""

import json
import math
from typing import Any

from trading.experiment_registry import ExperimentRegistry

CHECK_SECONDS = 10
STALE_SECONDS = 35
CONFIRM_SECONDS = 3
MAX_THREADS = 64


def operational_conditions(paper: Any, now: float) -> list[dict[str, Any]]:
    """Read existing in-memory producers only. Never run a model, quote request or ledger query."""
    fresh = bool(
        paper
        and paper.running
        and not paper.error
        and 0 <= now - paper.state.get("last_tick", 0) <= 10
    )
    fault = paper.error if paper else None
    rows = [
        {
            "key": "paper_processing",
            "condition": "active" if fault else "clear" if fresh else "unknown",
            "severity": "critical" if fault else "warning",
            "source_at": now,
            "title": "Paper processing and accounting status",
            "market": None,
            "account": None,
            "impact": "Current processing/accounting health is unconfirmed while unavailable",
            "next_action": "Inspect health and retained accounting; no restart is authorized",
            "link": "#risk",
            "facts": {
                "last_tick": paper.state.get("last_tick") if paper else None,
                "running": paper.running if paper else None,
                "reported_error": fault,
            },
        }
    ]
    status_reader = getattr(paper, "journal_status", None)
    journal = status_reader() if callable(status_reader) else {}
    journal_state = journal.get("status", "pending")
    journal_condition = {
        "key": "financial_monitoring",
        "condition": "clear" if journal_state == "balanced" else
        "active" if journal_state == "imbalanced" else "unknown",
        "severity": "critical" if journal_state == "imbalanced" else "warning",
        "source_at": now,
        "title": "Financial journal monitoring",
        "market": None, "account": None,
        "impact": "Last completed audit and current monitoring availability are separate",
        "next_action": "Inspect audit time, revision and current monitoring; preserve history",
        "link": "#accounts",
        "facts": {k: journal.get(k) for k in
                  ("status", "available", "balanced", "checked_at", "revision", "error",
                   "audit_age_seconds")},
    }
    guarded = getattr(paper, "constrained", None)
    rows.append(
        {
            "key": "research_resource",
            "condition": (
                "unknown"
                if not fresh or not callable(guarded)
                else "active"
                if guarded()
                else "clear"
            ),
            "severity": "warning",
            "source_at": now,
            "title": "Optional research admission",
            "market": None,
            "account": None,
            "impact": "Refused admission is not a model-quality failure",
            "next_action": "Inspect readiness and whole-work guard; preserve protection",
            "link": "#role-research",
            "facts": {
                "cooldown_until_mono": getattr(paper, "_constrained_until", None),
                "disk_free_bytes": getattr(paper, "disk_free", None),
                "capture_failure": getattr(paper, "_capture_failure", None),
            },
        }
    )
    capture_failure = getattr(paper, "_capture_failure", None)
    rows.append(
        {
            "key": "raw_recording",
            "condition": "unknown" if not fresh else ("active" if capture_failure else "clear"),
            "severity": "critical" if capture_failure else "warning",
            "source_at": now,
            "title": "Raw recording status",
            "market": None,
            "account": None,
            "impact": "A recording failure can leave original evidence incomplete",
            "next_action": "Inspect recording/storage status and preserve the original gap",
            "link": "#research",
            "facts": {"capture_failure": capture_failure},
        }
    )
    storage = getattr(getattr(paper, "evidence", None), "storage_status", {})
    state = storage.get("state")
    retained_fault = state in {"unavailable", "capacity", "disk_pressure"}
    rows.append(
        {
            "key": "retained_recording",
            "condition": "unknown"
            if not fresh or not (state == "recording" or retained_fault)
            else ("active" if retained_fault else "clear"),
            "severity": "critical" if retained_fault else "warning",
            "source_at": now,
            "title": "Retained evidence recording status",
            "market": None,
            "account": None,
            "impact": "A retained-evidence gap limits replay and empirical teaching claims",
            "next_action": "Inspect retained storage and its retry status; preserve original gaps",
            "link": "#research",
            "facts": {
                key: storage.get(key)
                for key in (
                    "state",
                    "reason",
                    "latest_reference",
                    "last_capture",
                    "full_omitted",
                    "compact_omitted",
                )
            },
        }
    )
    eligibility = getattr(paper, "_input_eligibility", {})
    source_at = eligibility.get("observed_at")
    input_fresh = fresh and isinstance(source_at, (int, float)) and 0 <= now - source_at <= 10
    for symbol in ("BTCUSD", "ETHUSD"):
        original = eligibility.get("markets", {}).get(symbol)
        known = input_fresh and isinstance(original, dict) and "frame_present" in original
        rows.append(
            {
                "key": "input:" + symbol,
                "condition": "unknown"
                if not known
                else "clear"
                if original["frame_present"]
                else "active",
                "severity": "warning",
                "source_at": source_at if known else now,
                "title": f"{symbol.removesuffix('USD')} / USD execution input coverage",
                "market": symbol,
                "account": None,
                "impact": "Missing inputs can prevent a supported test; missed profit is unknown",
                "next_action": "Inspect original input diagnosis; candles cannot replace a book",
                "link": f"#strategies?symbol={symbol}&account=primary",
                "facts": {
                    "selector": original if known else None,
                    "selector_observed_at": source_at,
                },
            }
        )
    rows.append(journal_condition)
    for row in rows:
        row["source_epoch"] = getattr(paper, "_notice_epoch", "legacy")
    return rows


class ResearchNotices:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        self.last_checked_at: float | None = None
        with registry.lock:
            registry.db.execute(
                "CREATE TABLE IF NOT EXISTS research_notices("
                "key TEXT PRIMARY KEY,body TEXT NOT NULL)"
            )
            registry.db.execute(
                "CREATE TABLE IF NOT EXISTS research_notice_epochs("
                "key TEXT NOT NULL,epoch TEXT NOT NULL,PRIMARY KEY(key,epoch))"
            )

    def observe(self, conditions: list[dict[str, Any]], now: float) -> None:
        if not math.isfinite(now) or len(conditions) > 8:
            raise ValueError("Use a finite bounded operational observation")
        # Optional presentation persistence must not wait indefinitely on shared
        # registry contention. The existing supervisor records failure and retries.
        if not self.registry.lock.acquire(timeout=1):
            raise OSError("Notice registry is busy; retry at the ordinary check")
        try:
            with self.registry.transaction():
                for condition in conditions:
                    self._observe(condition, now)
        finally:
            self.registry.lock.release()
        self.last_checked_at = now

    def _observe(self, condition: dict[str, Any], now: float) -> None:
        key = condition["key"]
        desired = condition["condition"]
        source_at = condition["source_at"]
        epoch = condition.get("source_epoch", "legacy")
        if (
            key
            not in {
                "paper_processing",
                "financial_monitoring",
                "research_resource",
                "raw_recording",
                "retained_recording",
                "input:BTCUSD",
                "input:ETHUSD",
            }
            or desired not in {"active", "clear", "unknown"}
            or not isinstance(source_at, (int, float))
            or isinstance(source_at, bool)
            or not math.isfinite(source_at)
            or source_at > now
            or condition["severity"] not in {"warning", "critical"}
            or not isinstance(epoch, str)
            or not 1 <= len(epoch) <= 80
            or len(json.dumps(condition, allow_nan=False).encode()) > 8192
        ):
            raise ValueError("Invalid or oversized operational condition")
        saved = self.registry.db.execute(
            "SELECT body FROM research_notices WHERE key=?", (key,)
        ).fetchone()
        if saved is None and desired == "clear":
            return  # Healthy polling alone does not create an alert.
        if saved is None:
            count = self.registry.db.execute("SELECT count(*) FROM research_notices").fetchone()[0]
            if count >= MAX_THREADS:
                raise ValueError("Notice projection is full; preserve history")
        row = (
            json.loads(saved[0])
            if saved
            else {
                "key": key,
                "state": "pending",
                "first_observed_at": source_at,
                "last_actual_occurrence": None,
                "last_source_at": None,
                "observations": 0,
                "active_observations": 0,
                "repeated_source_checks": 0,
                "notifications": 0,
                "recoveries": 0,
                "candidate": None,
                "candidate_since": now,
                "candidate_observations": 0,
                "acknowledged_at": None,
                "snoozed_until": 0,
                "severity": condition["severity"],
                "last_determinate_state": "pending",
            }
        )
        previous_epoch = row.get("last_source_epoch", "legacy")
        if "last_source_epoch" not in row:
            self.registry.db.execute(
                "INSERT OR IGNORE INTO research_notice_epochs VALUES(?,?)", (key, previous_epoch)
            )
        changed_epoch = epoch != previous_epoch
        if changed_epoch:
            if self.registry.db.execute(
                "SELECT 1 FROM research_notice_epochs WHERE key=? AND epoch=?", (key, epoch)
            ).fetchone():
                self._reject_source(row, condition, now, "A superseded producer epoch arrived")
                return
            self.registry.db.execute("INSERT INTO research_notice_epochs VALUES(?,?)", (key, epoch))
            row.update(last_source_at=None, candidate=None, candidate_observations=0)
            self.registry.event(
                "notice:" + key,
                "operational_source_epoch",
                {
                    "previous": previous_epoch,
                    "epoch": epoch,
                    "observed_at": source_at,
                    "projection_at": now,
                },
            )
        row["last_source_epoch"] = epoch
        if not changed_epoch and now < row.get("last_check_at", now):
            self._reject_source(row, condition, now, "Projection clock moved backwards")
            return
        if row["last_source_at"] is not None and source_at < row["last_source_at"]:
            self._reject_source(row, condition, now, "Source timestamp moved backwards")
            return
        repeated = row["last_source_at"] == source_at
        if repeated and desired != row.get("last_source_condition", row.get("candidate")):
            self._reject_source(
                row, condition, now, "One source timestamp describes different conditions"
            )
            return
        row["last_check_at"] = now
        row["source_error"] = None
        if repeated:
            row["repeated_source_checks"] += 1
        else:
            row["last_source_at"] = source_at
            row["last_source_condition"] = desired
            row["observations"] += 1
            if desired == "active":
                row["active_observations"] += 1
                row["last_actual_occurrence"] = source_at
            if row["candidate"] != desired:
                row.update(candidate=desired, candidate_since=now, candidate_observations=1)
            else:
                row["candidate_observations"] += 1
        ready = (
            desired == "unknown"
            or desired == "active"
            and condition["severity"] == "critical"
            or row["candidate"] == desired
            and row["candidate_observations"] >= 2
            and now - row["candidate_since"] >= CONFIRM_SECONDS
        )
        new_state = "recovered" if desired == "clear" else desired
        prior_severity = row["severity"]
        change = ready and (
            new_state != row["state"]
            or new_state == "active"
            and condition["severity"] != prior_severity
        )
        row["condition_evidence"] = condition
        row["current_condition"] = desired
        if change:
            previous = row["state"]
            previous_confirmed = row["last_determinate_state"]
            row.update(state=new_state, changed_at=now, acknowledged_at=None, snoozed_until=0)
            if new_state != "unknown":
                row.update(last_determinate_state=new_state, severity=condition["severity"])
            if new_state == "recovered":
                row["recoveries"] += 1
            elif new_state == "active" and (
                previous_confirmed != "active" or condition["severity"] != prior_severity
            ):
                row["notifications"] += 1
            self.registry.event(
                "notice:" + key,
                "operational_transition",
                {
                    "previous": previous,
                    "state": new_state,
                    "observed_at": source_at,
                    "projection_at": now,
                    "source": condition,
                },
            )
        self.registry.db.execute(
            "INSERT INTO research_notices VALUES(?,?) ON CONFLICT(key) "
            "DO UPDATE SET body=excluded.body",
            (key, json.dumps(row, sort_keys=True, allow_nan=False)),
        )

    def _reject_source(
        self, row: dict[str, Any], condition: dict[str, Any], now: float, reason: str
    ) -> None:
        previous = row["state"]
        row.update(
            state="unknown",
            current_condition="unknown",
            candidate=None,
            candidate_observations=0,
            source_error=reason,
            last_check_at=max(now, row.get("last_check_at", now)),
            last_rejected_source={
                "epoch": condition.get("source_epoch", "legacy"),
                "at": condition["source_at"],
                "condition": condition["condition"],
                "checked_at": now,
            },
        )
        row["invalid_source_checks"] = row.get("invalid_source_checks", 0) + 1
        if previous != "unknown":
            self.registry.event(
                "notice:" + row["key"],
                "operational_transition",
                {
                    "previous": previous,
                    "state": "unknown",
                    "projection_at": now,
                    "source": condition,
                    "source_error": reason,
                },
            )
        self.registry.db.execute(
            "UPDATE research_notices SET body=? WHERE key=?",
            (json.dumps(row, sort_keys=True, allow_nan=False), row["key"]),
        )

    def present(self, key: str, action: str, now: float, seconds: int = 0) -> dict[str, Any]:
        if action not in {"acknowledge", "snooze", "clear_presentation"} or seconds not in {
            0,
            300,
            900,
        }:
            raise ValueError("Unknown presentation action")
        with self.registry.transaction():
            found = self.registry.db.execute(
                "SELECT body FROM research_notices WHERE key=?", (key,)
            ).fetchone()
            if found is None:
                raise ValueError("Unknown operational thread")
            row = json.loads(found[0])
            if action == "acknowledge":
                row["acknowledged_at"] = now
            elif action == "snooze":
                row["snoozed_until"] = now + seconds
            else:
                row.update(acknowledged_at=None, snoozed_until=0)
            self.registry.db.execute(
                "UPDATE research_notices SET body=? WHERE key=?", (json.dumps(row), key)
            )
            self.registry.event(
                "notice:" + key,
                "notice_presentation",
                {"action": action, "at": now, "seconds": seconds},
            )
        return {"key": key, "presentation_only": True, "financial_or_service_effect": False}

    def snapshot(self, now: float) -> dict[str, Any]:
        """Metadata read only. Opening a lesson/task uses its existing disclosure path."""
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT body FROM research_notices ORDER BY key LIMIT 64"
            ).fetchall()
            operational = []
            for saved in rows:
                row = json.loads(saved[0])
                row["last_confirmed_state"] = row["last_determinate_state"]
                if not 0 <= now - row["last_check_at"] <= STALE_SECONDS:
                    row["state"] = "unavailable"
                row["suppressed_active_observations"] = max(
                    0, row["active_observations"] - row["notifications"]
                )
                operational.append(row)
            # Identifiers/times/status only: no hidden answers, grades, outcomes or lesson targets.
            tables = {
                r[0]
                for r in self.registry.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            developments = (
                [
                    dict(r)
                    for r in self.registry.db.execute(
                        "SELECT id,created,updated,stage,status FROM role_tasks "
                        "ORDER BY created DESC,id DESC LIMIT 6"
                    )
                ]
                if "role_tasks" in tables
                else None
            )
            findings = (
                [
                    dict(r)
                    for r in self.registry.db.execute(
                        "SELECT id,task,family,horizon,created,"
                        "json_extract(body,'$.source.body.available_at') "
                        "AS available_at FROM research_lessons WHERE "
                        "json_extract(body,'$.source.body.available_at')<=? "
                        "ORDER BY seq DESC LIMIT 6",
                        (now,),
                    )
                ]
                if "research_lessons" in tables
                else None
            )
        return {
            "queried_at": now,
            "operational": operational,
            "detector_last_check_at": self.last_checked_at,
            "developments": developments,
            "findings": findings,
            "population": {
                "maximum_threads": MAX_THREADS,
                "maximum_category_items": 5,
                "more_developments": len(developments) > 5 if developments is not None else None,
                "more_findings": len(findings) > 5 if findings is not None else None,
            },
            "basis": "Sampled producer checks, not all engine events or measured market benefit",
            "presentation": "Acknowledgment/snooze never resolves, unpauses, restarts or activates",
        } | {
            "developments": developments[:5] if developments is not None else None,
            "findings": findings[:5] if findings is not None else None,
        }

    def detail(self, key: str) -> dict[str, Any]:
        with self.registry.lock:
            if not self.registry.db.execute(
                "SELECT 1 FROM research_notices WHERE key=?", (key,)
            ).fetchone():
                raise ValueError("Original operational thread is unavailable")
            rows = self.registry.db.execute(
                "SELECT at,kind,body FROM experiment_events WHERE request_id=? "
                "ORDER BY seq DESC LIMIT 21",
                ("notice:" + key,),
            ).fetchall()
        return {
            "key": key,
            "transitions": [{**dict(r), "body": json.loads(r["body"])} for r in rows[:20]],
            "more_transitions": len(rows) > 20,
            "basis": "Original immutable observation/transition receipts",
        }
