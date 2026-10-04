"""Original research -> saved semantic review -> existing private Lab preparation."""

import importlib.util
import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_role_contract import contract_hash, packet_json
from trading.llm_training import (
    Candidate,
    Checked,
    Example,
    candidate_from_episode,
    candidate_from_market,
    prepare,
)
from trading.llm_training_preflight import preflight
from trading.role_worker import RoleWorker
from trading.storage import MonitorStore
from trading.training_bridge import TrainingBridge


class SourceSelection(Checked):
    kind: Literal["model_attempt", "observed_episode", "market_observation"]
    identity: str = Field(min_length=1, max_length=100)
    stage: Literal["idea", "review", "followup"] = "idea"
    attempt: int = Field(default=1, ge=1, le=100)
    question: str | None = Field(default=None, min_length=12, max_length=1000)
    author: str | None = Field(default=None, min_length=3, max_length=120)
    role: Literal["researcher", "reviewer"] = "researcher"


class ReviewSave(Checked):
    revision: int = Field(ge=0)
    disposition: Literal["draft", "accept", "correct", "exclude", "pending"]
    reason: str = Field(min_length=20, max_length=2000)
    lesson: str = Field(min_length=12, max_length=1000)
    target: dict[str, Any] | None
    review: dict[str, Any]
    rights_reason: str = Field(min_length=0, max_length=2000)


class DatasetSelection(Checked):
    ids: list[str] = Field(min_length=1, max_length=64)
    train_end: float = Field(ge=0)
    validation_end: float = Field(ge=0)
    embargo_seconds: float = Field(default=2700.0, ge=0)
    preparation_only: bool = True


class Retirement(Checked):
    study: str = Field(min_length=1, max_length=100)
    reviewer: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=20, max_length=2000)


def review_identity(body: dict[str, Any]) -> dict[str, Any]:
    return body | {"review": {k: v for k, v in body["review"].items() if k != "reviewed_at"}}


def public_protection() -> list[dict[str, Any]]:
    """Reuse the original published procedural protection; never sealed private targets."""
    path = Path(__file__).resolve().parents[2] / "scripts/llm_training_pilot.py"
    # The script imports its sibling published fixtures. Use its existing helper directly.
    import sys

    spec = importlib.util.spec_from_file_location("qtrades_public_training_protection", path)
    if spec is None or spec.loader is None:
        raise ValueError("Published qualification protection is unavailable")
    module = importlib.util.module_from_spec(spec)
    old = list(sys.path)
    try:
        sys.path.insert(0, str(path.parent))
        spec.loader.exec_module(module)
        return list(module.protected_packets())
    finally:
        sys.path[:] = old


class TrainingWorkflow:
    def __init__(
        self,
        registry: ExperimentRegistry,
        roles: RoleWorker | None,
        market: MonitorStore | None = None,
    ):
        self.registry, self.roles = registry, roles
        self.market = market
        self.bridge = TrainingBridge(registry.path.parent / "training-lab.json")
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS training_candidates (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, source TEXT NOT NULL,
                    candidate TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS training_reviews (
                    id TEXT NOT NULL, revision INTEGER NOT NULL, saved REAL NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS training_handoffs (
                    id TEXT PRIMARY KEY, selection_sha256 TEXT UNIQUE NOT NULL,
                    created REAL NOT NULL, body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_teaching_candidate
                    BEFORE UPDATE ON training_candidates
                    BEGIN SELECT RAISE(ABORT,'Original teaching evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_teaching_review
                    BEFORE UPDATE ON training_reviews
                    BEGIN SELECT RAISE(ABORT,'Review history is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS retain_teaching_candidate
                    BEFORE DELETE ON training_candidates
                    BEGIN SELECT RAISE(ABORT,'Original teaching evidence is permanent'); END;
                CREATE TRIGGER IF NOT EXISTS retain_teaching_review
                    BEFORE DELETE ON training_reviews
                    BEGIN SELECT RAISE(ABORT,'Review history is permanent'); END;
            """)

    def sources(self) -> dict[str, Any]:
        with self.registry.lock:
            episodes = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT request_id AS id,status,created,finished,reason,"
                    "json_extract(plan,'$.name') AS name,"
                    "json_extract(plan,'$.evidence_kind') AS basis "
                    "FROM experiments WHERE status IN "
                    "('completed','failed','cancelled','rejected') "
                    "AND finished IS NOT NULL ORDER BY seq DESC LIMIT 64"
                )
            ]
            attempts = (
                []
                if self.roles is None
                else [
                    dict(r)
                    for r in self.registry.db.execute(
                        "SELECT task AS id,stage,attempt,started,finished FROM role_attempts "
                        "WHERE finished IS NOT NULL AND response IS NOT NULL "
                        "ORDER BY started DESC LIMIT 64"
                    )
                ]
            )
            examples = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT c.id,c.created,c.source,r.revision,"
                    "json_extract(r.body,'$.disposition') AS disposition,"
                    "json_extract(r.body,'$.lesson') AS lesson FROM training_candidates c "
                    "LEFT JOIN training_reviews r ON r.id=c.id "
                    "AND r.revision=(SELECT MAX(revision) "
                    "FROM training_reviews WHERE id=c.id) ORDER BY c.created DESC LIMIT 128"
                )
            ]
            studies = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT id,created,json_extract(body,'$.stage') AS stage "
                    "FROM training_handoffs ORDER BY created DESC LIMIT 64"
                )
            ]
        observations = []
        if self.market is not None:
            with self.market.lock:
                observations = [
                    dict(r)
                    for r in self.market.db.execute(
                        "SELECT id,symbol,kind,observed_at FROM observations WHERE kind='depth' "
                        "ORDER BY id DESC LIMIT 32"
                    )
                ]
        for row in examples:
            row["source"] = json.loads(row["source"])
            row["disposition"] = row["disposition"] or "draft"
            row["lesson"] = row["lesson"] or "Not reviewed"
        try:
            cfg = self.bridge.configuration()
            configuration = {
                "available": True,
                "model": cfg["profile"]["name"],
                "studies": [
                    {"id": s["id"], "sealed": bool(s.get("sealed"))}
                    for s in cfg["policy"]["studies"]
                ],
                "comparisons": [
                    {"id": c["id"], "label": c["label"]} for c in cfg.get("comparisons", [])
                ],
            }
        except (ValueError, OSError, KeyError) as exc:
            configuration = {"available": False, "reason": str(exc)}
        return {
            "observations": observations,
            "episodes": episodes,
            "attempts": attempts,
            "examples": examples,
            "handoffs": studies,
            "configuration": configuration,
        }

    def select(self, source: SourceSelection) -> dict[str, Any]:
        if source.kind == "model_attempt":
            if self.roles is None:
                raise ValueError("Original model attempt registry is unavailable")
            candidate = self.roles.training_candidate(
                source.identity, source.stage, source.attempt
            )["candidate"]
        elif source.kind == "market_observation":
            if self.market is None or source.question is None or source.author is None:
                raise ValueError("Retained market source and newly authored question are required")
            with self.market.lock:
                row = self.market.db.execute(
                    "SELECT * FROM observations WHERE id=? AND kind='depth' "
                    "AND length(CAST(payload AS BLOB)) <= 90000",
                    (source.identity,),
                ).fetchone()
            if row is None:
                raise ValueError("Selected original observation is unavailable or oversized")
            record = dict(row)
            record["payload"] = json.loads(record["payload"])
            candidate = candidate_from_market(
                record,
                question=source.question,
                role=source.role,
                author=source.author,
                authored_at=time.time(),
            )["candidate"]
        else:
            if source.question is None or source.author is None:
                raise ValueError(
                    "Author the new question explicitly; the observation had no LLM question"
                )
            with self.registry.lock:
                row = self.registry.db.execute(
                    "SELECT request_id,plan,plan_sha256,code_sha256,created,finished,status,"
                    "snapshot_sha256,result,result_sha256,reason FROM experiments "
                    "WHERE request_id=? "
                    "AND length(CAST(plan AS BLOB)) <= 16384 "
                    "AND (result IS NULL OR length(CAST(result AS BLOB)) <= 100000)",
                    (source.identity,),
                ).fetchone()
            if row is None:
                raise ValueError("Selected episode is missing or exceeds the bounded source limit")
            record = dict(row)
            record["plan"] = json.loads(record["plan"])
            record["result"] = json.loads(record["result"]) if record["result"] else None
            if fingerprint(record["plan"]) != record["plan_sha256"] or (
                record["result"] is not None
                and fingerprint(record["result"]) != record["result_sha256"]
            ):
                raise ValueError("Retained original plan/result identity failed")
            candidate = candidate_from_episode(
                record,
                question=source.question,
                role=source.role,
                author=source.author,
                authored_at=time.time(),
            )["candidate"]
        Candidate.model_validate(candidate)
        identity = candidate["candidate_sha256"]
        with self.registry.transaction():
            self.registry.db.execute(
                "INSERT OR IGNORE INTO training_candidates VALUES (?,?,?,?)",
                (identity, time.time(), packet_json(source.model_dump()), packet_json(candidate)),
            )
        return self.detail(identity)

    def detail(self, identity: str, revision: int | None = None) -> dict[str, Any]:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM training_candidates WHERE id=?", (identity,)
            ).fetchone()
            reviews = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT revision,saved,json_extract(body,'$.disposition') AS disposition "
                    "FROM training_reviews WHERE id=? ORDER BY revision DESC LIMIT 32",
                    (identity,),
                )
            ]
            current = reviews[0]["revision"] if reviews else 0
            selected = self.registry.db.execute(
                "SELECT revision,saved,body FROM training_reviews WHERE id=? AND revision=?",
                (identity, current if revision is None else revision),
            ).fetchone()
        if row is None:
            raise ValueError("Saved teaching candidate is unavailable")
        if revision is not None and selected is None:
            raise ValueError("Requested saved review revision is unavailable")
        candidate = json.loads(row["candidate"])
        source = candidate.get("observed_source")
        available = source["available_at"] if source else candidate["decision_at"]
        initial = {
            "approved": True,
            "reviewer": "",
            "reviewer_kind": None,
            "reviewer_authored_material": None,
            "reviewed_at": None,
            "rationale": "",
            "rights_confirmed": False,
            "claim_scope": "interpretation",
            "data_basis": "synthetic"
            if source and source["evidence_basis"] == "synthetic_qa"
            else "observed"
            if source
            else "instructional"
            if candidate.get("source_kind") == "instructional"
            else "prospective",
            "family_ids": candidate["group_ids"],
            "categories": [],
            "episode_start": source["observed_start"] if source else candidate["decision_at"],
            "episode_end": source["observed_end"] if source else candidate["decision_at"],
            "target_available_at": available,
            "evidence_available_at": {k: available for k in candidate["packet"]["evidence"]},
        }
        saved = (
            {
                "revision": selected["revision"],
                "saved": selected["saved"],
                **json.loads(selected["body"]),
            }
            if selected
            else None
        )
        return {
            "id": identity,
            "candidate": candidate,
            "source": json.loads(row["source"]),
            "revision": selected["revision"] if selected else 0,
            "current_revision": current,
            "historical_revision": revision is not None,
            "saved": saved,
            "review_template": initial,
            "history": reviews,
        }

    def save(self, identity: str, draft: ReviewSave) -> dict[str, Any]:
        if len(packet_json(draft.model_dump()).encode()) > 262144:
            raise ValueError("Review exceeds the bounded allowance; nothing was saved")
        detail = self.detail(identity)
        body = draft.model_dump(exclude={"revision"})
        if draft.disposition in {"accept", "correct"}:
            if len(draft.rights_reason.strip()) < 20:
                raise ValueError("Record the applicable rights/usage basis before approval")
            review = draft.review | {
                "reviewed_at": time.time(),
                "rationale": draft.reason,
                "approved": True,
            }
            Example.model_validate(
                {"candidate": detail["candidate"], "review": review, "target": draft.target}
            )
            body["review"] = review
        with self.registry.transaction():
            last = self.registry.db.execute(
                "SELECT revision,body FROM training_reviews WHERE id=? "
                "ORDER BY revision DESC LIMIT 1",
                (identity,),
            ).fetchone()
            current = last["revision"] if last else 0
            if current != draft.revision:
                # A retried save cannot overwrite a concurrent reviewer revision.
                if last and review_identity(json.loads(last["body"])) == review_identity(body):
                    return self.detail(identity)
                raise ValueError("Review changed in another view; reopen before saving")
            self.registry.db.execute(
                "INSERT INTO training_reviews VALUES (?,?,?,?)",
                (identity, current + 1, time.time(), packet_json(body)),
            )
        return self.detail(identity)

    def rows(
        self, selection: DatasetSelection
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if len(set(selection.ids)) != len(selection.ids):
            raise ValueError("Select each teaching example once")
        rows, problems = [], []
        for identity in selection.ids:
            detail = self.detail(identity)
            saved = detail["saved"]
            if not saved or saved["disposition"] not in {"accept", "correct"}:
                problems.append(
                    {
                        "id": identity,
                        "code": "unapproved_disposition",
                        "reason": "Draft, pending and excluded reviews cannot enter training",
                    }
                )
            rows.append(
                {
                    "candidate": detail["candidate"],
                    "review": saved["review"] if saved else detail["review_template"],
                    "target": saved["target"] if saved else None,
                }
            )
        return rows, problems

    def preflight(self, selection: DatasetSelection) -> dict[str, Any]:
        rows, problems = self.rows(selection)
        return self._preflight(selection, rows, problems)

    def _preflight(
        self,
        selection: DatasetSelection,
        rows: list[dict[str, Any]],
        problems: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = preflight(
            rows, **selection.model_dump(exclude={"ids"}), protected_packets=public_protection()
        )
        result["problems"] += problems
        try:
            exposure, _ = self.bridge.dispatch(
                {"operation": "exposure", "metadata": result["metadata"]}
            )
            result["problems"] += exposure["problems"]
            result["exposure"] = exposure
        except (ValueError, OSError, KeyError) as exc:
            result["problems"].append({"id": None, "code": "lab_unavailable", "reason": str(exc)})
        result["eligible"] = not result["problems"]
        return result

    def build(self, selection: DatasetSelection) -> dict[str, Any]:
        # Freeze one local snapshot. Preflight and export use these same reviewed rows.
        with self.registry.lock:
            rows, problems = self.rows(selection)
            revisions = {identity: self.detail(identity)["revision"] for identity in selection.ids}
        key = fingerprint({"selection": selection.model_dump(), "rows": rows})
        with self.registry.lock:
            existing = self.registry.db.execute(
                "SELECT body FROM training_handoffs WHERE selection_sha256=?", (key,)
            ).fetchone()
        if existing:
            old = json.loads(existing[0])
            if old["stage"] == "prepared":
                return self.result(old["id"])
            if old["stage"] == "preparing":
                raise ValueError(
                    "Preparation is in flight or interrupted; inspect its retained attempt"
                )
            raise ValueError("Prior preparation failed; use explicit retry of its retained handoff")
        check = self._preflight(selection, rows, problems)
        if not check["eligible"]:
            return {"stage": "refused", "preflight": check}
        bundle = prepare(
            rows, **selection.model_dump(exclude={"ids"}), protected_packets=public_protection()
        )
        source_reviews = {
            row["candidate"]["candidate_sha256"]: {
                "revision": revisions[row["candidate"]["candidate_sha256"]],
                "review_sha256": fingerprint(row["review"]),
                "target_sha256": fingerprint(row["target"]),
            }
            for origins in bundle["provenance"].values()
            for row in origins
        }
        bundle["manifest"]["source_reviews"] = source_reviews
        cfg = self.bridge.configuration()
        identity = uuid.uuid4().hex
        now = time.time()
        state = {
            "id": identity,
            "stage": "preparing",
            "selection": selection.model_dump(),
            "selection_sha256": key,
            "attempts": [{"job": uuid.uuid4().hex, "stage": "requested", "at": now}],
            "source_examples": selection.ids,
            "source_reviews": source_reviews,
            "preflight": check,
        }
        with self.registry.transaction():
            if self.registry.db.execute(
                "SELECT 1 FROM training_handoffs WHERE selection_sha256=?", (key,)
            ).fetchone():
                raise ValueError("Preparation was claimed by another request; reopen its handoff")
            self.registry.db.execute(
                "INSERT INTO training_handoffs VALUES (?,?,?,?)",
                (identity, key, now, packet_json(state)),
            )
        return self._prepare(state, bundle, cfg)

    def _prepare(
        self, state: dict[str, Any], bundle: dict[str, Any], cfg: dict[str, Any]
    ) -> dict[str, Any]:
        # Ownership is committed before dispatch. Never hold the registry lock during Lab work.
        job_id = state["attempts"][-1]["job"]
        expected = {
            "study_id": state["id"],
            "run_id": job_id,
            "model_sha256": cfg["model_sha256"],
            "contract_sha256": contract_hash(),
            "source_examples": state["source_examples"],
        }
        if "source_reviews" in state:
            expected["source_reviews"] = state["source_reviews"]
        try:
            receipt, _ = self.bridge.dispatch(
                {"operation": "prepare", "expected": expected}, bundle, job_id
            )
        except (ValueError, OSError, KeyError) as exc:
            return self._finish(state["id"], job_id, reason=str(exc))
        return self._finish(state["id"], job_id, receipt=receipt)

    def _finish(
        self,
        identity: str,
        job_id: str,
        *,
        receipt: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with self.registry.transaction():
            state = self._saved(identity)
            attempt = next((a for a in state["attempts"] if a["job"] == job_id), None)
            if attempt is None:
                raise ValueError("Preparation completion has no retained ownership claim")
            if attempt["stage"] not in {"requested", "interrupted"}:
                raise ValueError("Preparation attempt already completed; reopen its saved result")
            outcome = "prepared" if receipt is not None else "failed"
            attempt.update(stage=outcome, finished=time.time())
            if receipt is not None:
                attempt["receipt_sha256"] = fingerprint(receipt)
            else:
                attempt["reason"] = reason
            if state["attempts"][-1]["job"] == job_id:
                state["stage"] = outcome
                if receipt is not None:
                    state.update(receipt=receipt, job_id=job_id)
                    state.pop("reason", None)
                else:
                    state["reason"] = reason
            else:
                # Keep the late outcome linked without replacing a newer attempt's result.
                attempt["superseded"] = True
            self.registry.db.execute(
                "UPDATE training_handoffs SET body=? WHERE id=?", (packet_json(state), identity)
            )
        return state

    def _saved(self, identity: str) -> dict[str, Any]:
        row = self.registry.db.execute(
            "SELECT body FROM training_handoffs WHERE id=?", (identity,)
        ).fetchone()
        if not row:
            raise ValueError("Saved preparation is unavailable")
        state: dict[str, Any] = json.loads(row[0])
        return state

    def _check_retry(self, state: dict[str, Any], created: float) -> None:
        if state["stage"] not in {"failed", "preparing"}:
            raise ValueError("Preparation changed; reopen its saved result")
        if state["stage"] == "preparing":
            since = state["attempts"][-1]["at"] if state["attempts"] else created
            if time.time() - since <= 190:
                raise ValueError("Preparation remains within its bounded request window")

    def _claim_retry(self, expected: dict[str, Any]) -> dict[str, Any]:
        with self.registry.transaction():
            state = self._saved(expected["id"])
            created = self.registry.db.execute(
                "SELECT created FROM training_handoffs WHERE id=?", (state["id"],)
            ).fetchone()[0]
            self._check_retry(state, created)
            if state["attempts"] != expected["attempts"] or state["stage"] != expected["stage"]:
                raise ValueError("Preparation changed; reopen its saved result")
            selection = DatasetSelection.model_validate(state["selection"])
            rows, problems = self.rows(selection)
            if (
                problems
                or fingerprint({"selection": selection.model_dump(), "rows": rows})
                != state["selection_sha256"]
            ):
                raise ValueError(
                    "Reviewed selection changed; retain this handoff and build a new one"
                )
            now = time.time()
            if state["attempts"] and state["attempts"][-1]["stage"] == "requested":
                state["attempts"][-1].update(
                    stage="interrupted",
                    interrupted_at=now,
                    reason="Request window expired; prior dispatched outcome remains unknown",
                )
            if not state["attempts"]:
                state["recovery"] = {
                    "at": now,
                    "reason": "Legacy handoff creation interrupted before any attempt was recorded",
                }
            state["attempts"].append({"job": uuid.uuid4().hex, "stage": "requested", "at": now})
            state["stage"] = "preparing"
            self.registry.db.execute(
                "UPDATE training_handoffs SET body=? WHERE id=?", (packet_json(state), state["id"])
            )
        return state

    def retry(self, identity: str) -> dict[str, Any]:
        state = self.result(identity)
        if state["stage"] not in {"failed", "preparing"}:
            return state
        # A live concurrent request is not retryable; only a bounded expired preparation is.
        with self.registry.lock:
            created = self.registry.db.execute(
                "SELECT created FROM training_handoffs WHERE id=?", (identity,)
            ).fetchone()[0]
        self._check_retry(state, created)
        selection = DatasetSelection.model_validate(state["selection"])
        rows, problems = self.rows(selection)
        if (
            problems
            or fingerprint({"selection": selection.model_dump(), "rows": rows})
            != state["selection_sha256"]
        ):
            raise ValueError("Reviewed selection changed; retain this handoff and build a new one")
        result = self.preflight(selection)
        if not result["eligible"]:
            return {"stage": "refused", "preflight": result}
        bundle = prepare(
            rows, **selection.model_dump(exclude={"ids"}), protected_packets=public_protection()
        )
        if "source_reviews" in state:
            bundle["manifest"]["source_reviews"] = state["source_reviews"]
        cfg = self.bridge.configuration()
        state = self._claim_retry(state)
        return self._prepare(state, bundle, cfg)

    def result(self, identity: str) -> dict[str, Any]:
        with self.registry.lock:
            state = self._saved(identity)
        if state["stage"] == "prepared":
            try:
                receipt = self.bridge.reopen(state["job_id"])
                if receipt != state["receipt"] or receipt["study_id"] != identity:
                    raise ValueError("Linked result conflicts with its saved handoff")
                state["archive_available"] = True
            except (ValueError, OSError, KeyError) as exc:
                state.update(archive_available=False, archive_reason=str(exc))
        return state

    def retire(self, request: Retirement) -> dict[str, Any]:
        receipt, job = self.bridge.dispatch(
            {
                "operation": "retire",
                "retirement": request.model_dump()
                | {"splits": ["validation", "test", "unknown_legacy"], "at": time.time()},
            }
        )
        cfg = self.bridge.configuration()
        cfg["policy"].setdefault("retirements", []).append(
            f"qtrades-handoffs/{job}/retirement.json"
        )
        # This changes exposure policy only, retaining original frozen manifests and targets.
        temp = self.bridge.config_path.with_suffix(".tmp")
        temp.write_text(packet_json(cfg) + "\n", encoding="utf-8")
        temp.replace(self.bridge.config_path)
        return receipt

    def comparison(self, identity: str) -> dict[str, Any]:
        cfg = self.bridge.configuration()
        link = next((c for c in cfg.get("comparisons", []) if c["id"] == identity), None)
        if link is None:
            raise ValueError("Select a verified existing comparison link")
        receipt, _ = self.bridge.dispatch({"operation": "comparison", "comparison_link": link})
        if (
            receipt.get("format") != "llm-lab-linked-comparison-v1"
            or receipt.get("dataset_sha256") != link["dataset_sha256"]
            or receipt.get("model_sha256") != link["model_sha256"]
            or receipt.get("run_id") != identity
        ):
            raise ValueError("Returned evaluation has conflicting source/model/run linkage")
        return {
            "id": identity,
            "stage": "evaluated",
            "receipt": receipt,
            "archive_available": True,
            "historical": True,
            "attempts": [],
        }
