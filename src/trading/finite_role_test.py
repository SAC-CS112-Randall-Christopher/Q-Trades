"""Permanent finite-test claims in the existing role registry, without a counter."""

import json
import math
import re
from typing import Any

from trading.experiment_registry import ExperimentRegistry
from trading.lab_role_contract import PATTERN_VERSION, contract_hash
from trading.pattern_comparisons import PatternFindingSelection

AUTHORITY_FIELDS = {
    "grant_id",
    "grant_sha",
    "profile_sha",
    "contract_version",
    "contract_sha",
    "question_policy",
}


def _epoch(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def finite_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != AUTHORITY_FIELDS | {"finite_test"}:
        raise ValueError("Finite test requires its exact grant authority")
    if (
        not all(isinstance(value[key], str) for key in AUTHORITY_FIELDS)
        or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value["grant_id"])
        or any(
            not re.fullmatch(r"[a-f0-9]{64}", value[k])
            for k in ("grant_sha", "profile_sha", "contract_sha")
        )
        or value["contract_version"] != PATTERN_VERSION
        or value["contract_sha"] != contract_hash(PATTERN_VERSION)
        or value["question_policy"] != "pattern-question-selection-v1"
    ):
        raise ValueError("Finite test authority is outside the supported pattern contract")
    test = value["finite_test"]
    if not isinstance(test, dict) or set(test) != {
        "not_before",
        "expires_at",
        "max_requests",
        "selection",
        "finding_sha256",
    }:
        raise ValueError("Finite test requires its exact limits and original finding")
    start, end = test["not_before"], test["expires_at"]
    if (
        any(not _epoch(v) for v in (start, end))
        or not start < end <= start + 30 * 3600
        or type(test["max_requests"]) is not int
        or test["max_requests"] != 3
        or not isinstance(test["finding_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", test["finding_sha256"])
    ):
        raise ValueError(
            "Finite test requires three requests within its original thirty-hour bound"
        )
    selection = PatternFindingSelection.model_validate(test["selection"])
    if selection.symbol != "BTCUSD" or selection.timeframe != "5m":
        raise ValueError(
            "Finite test supports only the exact saved BTCUSD native-five-minute finding"
        )
    return dict(json.loads(json.dumps(value, sort_keys=True, allow_nan=False)))


def active(scope: dict[str, Any], now: float) -> None:
    test = scope["finite_test"]
    if not _epoch(now) or not test["not_before"] <= now < test["expires_at"]:
        raise ValueError("Finite test is outside its original authorization window")


class FiniteRoleTest:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS role_finite_tests(
                    grant_id TEXT PRIMARY KEY,root_task TEXT UNIQUE NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS role_finite_tasks(
                    task TEXT PRIMARY KEY,grant_id TEXT NOT NULL,root_task TEXT NOT NULL,
                    body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS role_finite_root
                  ON role_finite_tasks(grant_id,root_task);
                CREATE TRIGGER IF NOT EXISTS role_finite_test_frozen
                  BEFORE UPDATE ON role_finite_tests
                  BEGIN SELECT RAISE(ABORT,'Finite grant claim is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS role_finite_test_retained
                  BEFORE DELETE ON role_finite_tests
                  BEGIN SELECT RAISE(ABORT,'Finite grant claim is permanent'); END;
                CREATE TRIGGER IF NOT EXISTS role_finite_task_frozen
                  BEFORE UPDATE ON role_finite_tasks
                  BEGIN SELECT RAISE(ABORT,'Finite task scope is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS role_finite_task_retained
                  BEFORE DELETE ON role_finite_tasks
                  BEGIN SELECT RAISE(ABORT,'Finite task scope is permanent'); END;
            """)
            columns = {r[1] for r in registry.db.execute("PRAGMA table_info(role_attempts)")}
            if "dispatch_started" not in columns:
                registry.db.execute("ALTER TABLE role_attempts ADD COLUMN dispatch_started REAL")
            registry.db.execute("""
                CREATE TRIGGER IF NOT EXISTS role_finite_dispatch_frozen
                BEFORE UPDATE OF dispatch_started ON role_attempts
                WHEN OLD.dispatch_started IS NOT NULL
                  AND NEW.dispatch_started IS NOT OLD.dispatch_started
                BEGIN SELECT RAISE(ABORT,'Attempt dispatch identity is immutable'); END
            """)

    def prior(self, scope: dict[str, Any]) -> dict[str, Any] | None:
        row = self.registry.db.execute(
            "SELECT root_task,body FROM role_finite_tests WHERE grant_id=?", (scope["grant_id"],)
        ).fetchone()
        if row is None:
            return None
        saved = json.loads(row["body"])
        if saved != scope:
            raise ValueError("Finite grant identity already belongs to a different original scope")
        return {"root_task": row["root_task"], **saved}

    def binding(self, task: dict[str, Any]) -> dict[str, Any]:
        row = self.registry.db.execute(
            "SELECT f.root_task,f.body,c.body AS claim,c.root_task AS claimed_root "
            "FROM role_finite_tasks f "
            "LEFT JOIN role_finite_tests c ON c.grant_id=f.grant_id WHERE f.task=?",
            (task["id"],),
        ).fetchone()
        if row is None or row["claim"] is None:
            raise ValueError("Finite task has no permanent original grant claim")
        saved = json.loads(row["body"])
        claim = finite_scope(json.loads(row["claim"]))
        if (
            saved != {**claim, "root_task": row["root_task"]}
            or row["root_task"] != row["claimed_root"]
            or task["context"].get("finite_test") != saved
            or task["context"].get("selection_authority") != {k: claim[k] for k in AUTHORITY_FIELDS}
        ):
            raise ValueError("Finite task differs from its immutable original root and authority")
        return dict(saved)

    def claim(
        self,
        scope: dict[str, Any],
        task: str,
        context: dict[str, Any],
        now: float,
        predecessor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Caller publishes this claim and role task in the same registry transaction."""
        active(scope, now)
        finding = context.get("pattern_comparison", {})
        if (
            finding.get("selection") != scope["finite_test"]["selection"]
            or finding.get("finding_sha256") != scope["finite_test"]["finding_sha256"]
            or context.get("question", {}).get("horizon") != "medium"
            or set(context.get("catalog", {})) != {"p0"}
            or context.get("selection_authority") != {k: scope[k] for k in AUTHORITY_FIELDS}
        ):
            raise ValueError(
                "Finite task requires only its exact original finding and fixed p0 method"
            )
        prior = self.prior(scope)
        if predecessor is None:
            if prior is not None and prior["root_task"] != task:
                raise ValueError("Finite test already claimed its one original research chain")
            root = task
            self.registry.db.execute(
                "INSERT OR IGNORE INTO role_finite_tests VALUES(?,?,?)",
                (scope["grant_id"], root, json.dumps(scope, sort_keys=True, allow_nan=False)),
            )
        else:
            original = self.binding(predecessor)
            if prior is None or original != prior:
                raise ValueError("Finite descendant requires its exact original root")
            root = original["root_task"]
            children = self.registry.db.execute(
                "SELECT count(*) FROM role_finite_tasks WHERE grant_id=? AND root_task=?",
                (scope["grant_id"], root),
            ).fetchone()[0]
            if children >= 20:
                raise ValueError("Finite chain reached the existing bounded lineage limit")
        body = {**scope, "root_task": root}
        self.registry.db.execute(
            "INSERT OR IGNORE INTO role_finite_tasks VALUES(?,?,?,?)",
            (task, scope["grant_id"], root, json.dumps(body, sort_keys=True, allow_nan=False)),
        )
        retained = self.registry.db.execute(
            "SELECT body FROM role_finite_tasks WHERE task=?", (task,)
        ).fetchone()
        if json.loads(retained["body"]) != body:
            raise ValueError("Finite task identity already belongs to another root")
        return body

    def count(self, binding: dict[str, Any]) -> int:
        return int(
            self.registry.db.execute(
                "SELECT count(*) FROM role_attempt_allowances a JOIN role_finite_tasks f "
                "ON f.task=a.task WHERE f.grant_id=? AND f.root_task=? AND a.actor IS NULL",
                (binding["grant_id"], binding["root_task"]),
            ).fetchone()[0]
        )
