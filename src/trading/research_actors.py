"""Explicit task grants sharing the existing optional-role leases and proposal path."""

import hashlib
import json
import secrets
import time
from contextlib import nullcontext
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trading.experiment_registry import fingerprint
from trading.lab_role_contract import VERSION, validate
from trading.research_storage import storage_snapshot
from trading.role_worker import RoleWorker


class ActorGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actor: str = Field(pattern=r"^[A-Za-z0-9_-]{3,60}$")
    tasks: list[str] = Field(min_length=1, max_length=8)
    lifetime_seconds: int = Field(default=3600, ge=60, le=7200)
    output_bytes: int = Field(default=65536, ge=8192, le=262144)
    requests: int = Field(default=20, ge=1, le=100)
    processing_location: str = Field(min_length=3, max_length=150)


class ActorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claim: str = Field(pattern=r"^[a-f0-9]{32}$")
    answer: dict[str, Any]


class ActorTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task: str = Field(pattern=r"^role-[a-f0-9]{32}$")


class ActorClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claim: str = Field(pattern=r"^[a-f0-9]{32}$")


class ResearchActors:
    def __init__(self, worker: RoleWorker):
        self.worker, self.registry = worker, worker.registry
        with self.registry.lock:
            self.registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS research_actors(
                    id TEXT PRIMARY KEY,token_sha TEXT UNIQUE NOT NULL,actor TEXT NOT NULL,
                    expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,
                    scope TEXT NOT NULL,output_limit INTEGER NOT NULL,
                    request_limit INTEGER NOT NULL,output_used INTEGER NOT NULL DEFAULT 0,
                    requests_used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS actor_claims(
                    id TEXT PRIMARY KEY,grant_id TEXT NOT NULL,
                    task TEXT NOT NULL,stage TEXT NOT NULL,
                    attempt INTEGER NOT NULL,started REAL NOT NULL,lease_until REAL NOT NULL,
                    packet_sha TEXT NOT NULL,response_sha TEXT,status TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS actor_claim_history ON actor_claims(task,stage,started);
            """)

    def grant(self, grant: ActorGrant) -> dict[str, Any]:
        for identity in grant.tasks:
            self.worker.get(identity)
        token = secrets.token_urlsafe(32)
        identity = "grant-" + secrets.token_hex(16)
        with self.registry.transaction():
            if (
                self.registry.db.execute("SELECT count(*) FROM research_actors").fetchone()[0]
                >= 4096
            ):
                raise ValueError(
                    "Retained grant identity capacity reached; no credential history pruned"
                )
            if (
                self.registry.db.execute(
                    "SELECT count(*) FROM research_actors WHERE revoked=0 AND expires>?",
                    (time.time(),),
                ).fetchone()[0]
                >= 16
            ):
                raise ValueError(
                    "Sixteen retained active grants; revoke/expire before issuing more"
                )
            self.registry.db.execute(
                "INSERT INTO research_actors(id,token_sha,actor,expires,scope,"
                "output_limit,request_limit) VALUES(?,?,?,?,?,?,?)",
                (
                    identity,
                    hashlib.sha256(token.encode()).hexdigest(),
                    grant.actor,
                    time.time() + grant.lifetime_seconds,
                    json.dumps(grant.model_dump()),
                    grant.output_bytes,
                    grant.requests,
                ),
            )
        return {
            "id": identity,
            "token": token,
            "actor": grant.actor,
            "scope": grant.model_dump(),
            "authority": "Researcher/follow-up only; required local review and paper engine",
            "activation": "A grant does not enable local inference or an external worker",
        }

    def auth(self, token: str, task: str | None = None) -> dict[str, Any]:
        if not 20 <= len(token) <= 200:
            raise ValueError("Research credential unavailable")
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM research_actors WHERE token_sha=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        if not row or row["revoked"] or row["expires"] <= time.time():
            raise ValueError("Research credential expired or revoked")
        actor = dict(row)
        actor["scope"] = json.loads(actor["scope"])
        if task is not None and task not in actor["scope"]["tasks"]:
            raise ValueError("Task is outside the server-issued grant")
        return actor

    def revoke(self, identity: str) -> None:
        with self.registry.transaction():
            if not self.registry.db.execute(
                "UPDATE research_actors SET revoked=1 WHERE id=?", (identity,)
            ).rowcount:
                raise ValueError("Unknown research grant")
            # Already answered receipts and all accounts remain untouched. Pending
            # remote completion becomes explicit unknown work rather than a hidden retry.
            claims = self.registry.db.execute(
                "SELECT * FROM actor_claims WHERE grant_id=? AND status='claimed'", (identity,)
            ).fetchall()
            for claim in claims:
                self._release(claim, "Credential revoked; external completion unknown")

    def snapshot(self) -> dict[str, Any]:
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT id,actor,expires,revoked,scope,output_limit,request_limit,"
                "output_used,requests_used FROM research_actors "
                "ORDER BY CASE WHEN revoked=0 AND expires>? THEN 0 ELSE 1 END,"
                "expires DESC LIMIT 20",
                (time.time(),),
            ).fetchall()
        return {
            "grants": [dict(row) | {"scope": json.loads(row["scope"])} for row in rows],
            "transport": (
                "Local scoped HTTP adapter only; "
                "no installed Crik connector/authorized bridge configured"
            ),
            "data_scope": (
                "Explicit frozen semantic task packet and granted result; "
                "no raw archives, credentials or held-out data"
            ),
            "allowance": (
                "Two concurrent external claims; 600 reserved seconds and "
                "32768 conservative tokens per hour; per-grant output/request caps"
            ),
            "maintenance": (
                "No external migration, expiry, deletion, financial or training-weight capabilities"
            ),
        }

    def _charge(self, actor: dict[str, Any], size: int) -> None:
        # Callers mutating a claim already own the registry transaction. Read-only
        # deliveries use a standalone transaction; the lock prevents another
        # thread's transaction from being mistaken for our own.
        with self.registry.lock:
            with nullcontext() if self.registry.db.in_transaction else self.registry.transaction():
                changed = self.registry.db.execute(
                    "UPDATE research_actors SET output_used=output_used+?,"
                    "requests_used=requests_used+1 "
                    "WHERE id=? AND revoked=0 AND expires>? AND output_used+?<=output_limit "
                    "AND requests_used<request_limit",
                    (size, actor["id"], time.time(), size),
                ).rowcount
                if not changed:
                    raise ValueError(
                        "Research grant allowance exhausted/revoked; no data delivered"
                    )

    def claim(self, token: str, task_id: str) -> dict[str, Any]:
        actor = self.auth(token, task_id)
        task = self.worker.get(task_id)
        self.worker._current(task)
        role, packet = self.worker._packet(task)
        if (
            role != "researcher"
            or task["stage"] not in {"idea", "followup"}
            or task["status"] in {"done", "failed"}
        ):
            raise ValueError("Only eligible researcher/follow-up stages may be externally claimed")
        encoded = json.dumps(packet, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 24576:
            raise ValueError("Task packet exceeds the scoped external allowance")
        now, claim_id = time.time(), secrets.token_hex(16)
        until = min(now + 90, actor["expires"])
        result = {
            "claim": claim_id,
            "task": task_id,
            "stage": task["stage"],
            "lease_until": until,
            "contract": VERSION,
            "packet": packet,
            "packet_sha256": fingerprint(packet),
            "scope": "This frozen semantic packet only; no raw archives/heldout/credentials",
            "required_review": "External output cannot fund or qualify a paper account",
        }
        with self.registry.transaction():
            actor = self.auth(token, task_id)
            now = time.time()
            until = min(now + 90, actor["expires"])
            result["lease_until"] = until
            if (
                self.registry.db.execute(
                    "SELECT count(*) FROM actor_claims WHERE status='claimed' AND lease_until>=?",
                    (now,),
                ).fetchone()[0]
                >= 2
            ):
                raise ValueError(
                    "Two external claims active; independent local research retains capacity"
                )
            used = self.registry.db.execute(
                "SELECT coalesce(sum(wall_reserved),0),coalesce(sum(tokens_reserved),0) "
                "FROM role_attempts WHERE started>=? "
                "AND json_extract(profile,'$.actor') IS NOT NULL",
                (now - 3600,),
            ).fetchone()
            if used[0] + 90 > 600 or used[1] + 8192 > 32768:
                raise ValueError(
                    "Separate external hourly allowance exhausted; retained across reconnect"
                )
            previous = self.registry.db.execute(
                "SELECT * FROM role_attempts WHERE task=? AND stage=? "
                "ORDER BY attempt DESC LIMIT 1",
                (task_id, task["stage"]),
            ).fetchone()
            if previous and (
                previous["response"] is not None
                or previous["status"] != "retry_authorized"
                or previous["attempt"] >= 2
            ):
                raise ValueError(
                    "Completed/unknown prior answer retained; explicit bounded retry required"
                )
            changed = self.registry.db.execute(
                "UPDATE role_tasks SET owner=?,lease_until=?,status='running' WHERE id=? "
                "AND stage=? AND status NOT IN ('done','failed') "
                "AND (owner IS NULL OR lease_until<?)",
                ("actor:" + claim_id, until, task_id, task["stage"], now),
            ).rowcount
            if not changed:
                raise ValueError("Task already owned; local and external claims share one lease")
            attempt = previous["attempt"] + 1 if previous else 1
            profile = {
                "actor": actor["actor"],
                "grant_id": actor["id"],
                "contract": VERSION,
                "processing_location": actor["scope"]["processing_location"],
                "qualification": "External contributor unverified; required local qualified review",
                "tokens": "Unknown; conservative external allowance reserved",
            }
            self.registry.db.execute(
                "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,"
                "packet,wall_reserved,tokens_reserved) "
                "VALUES(?,?,?,?,'external_pending',?,?,90,8192)",
                (task_id, task["stage"], attempt, now, json.dumps(profile), encoded),
            )
            self.registry.db.execute(
                "INSERT INTO actor_claims VALUES(?,?,?,?,?,?,?, ?,NULL,'claimed')",
                (
                    claim_id,
                    actor["id"],
                    task_id,
                    task["stage"],
                    attempt,
                    now,
                    until,
                    fingerprint(packet),
                ),
            )
            self._charge(actor, len(json.dumps(result, allow_nan=False).encode()))
            self.auth(token, task_id)  # Expiry at settlement rolls back every effect.
        # Follow-up outcome protection commits before the granted packet leaves.
        self.worker.view(task_id)
        return result

    def _claim(self, actor: dict[str, Any], claim_id: str) -> dict[str, Any]:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM actor_claims WHERE id=? AND grant_id=?", (claim_id, actor["id"])
            ).fetchone()
        if not row:
            raise ValueError("Claim belongs to another grant or is unknown")
        return dict(row)

    def renew(self, token: str, claim_id: str) -> dict[str, Any]:
        with self.registry.transaction():
            return self._renew(token, claim_id)

    def _renew(self, token: str, claim_id: str) -> dict[str, Any]:
        actor = self.auth(token)
        claim = self._claim(actor, claim_id)
        self.auth(token, claim["task"])
        now = time.time()
        if (
            claim["status"] != "claimed"
            or claim["lease_until"] < now
            or claim["started"] + 300 <= now
        ):
            raise ValueError("Expired/completed claim cannot be renewed")
        until = min(now + 90, claim["started"] + 300, actor["expires"])
        result = {"claim": claim_id, "lease_until": until}
        with self.registry.lock:
            used = self.registry.db.execute(
                "SELECT coalesce(sum(wall_reserved),0) FROM role_attempts "
                "WHERE started>=? AND json_extract(profile,'$.actor') IS NOT NULL",
                (now - 3600,),
            ).fetchone()[0]
            attempt = self.registry.db.execute(
                "SELECT wall_reserved FROM role_attempts WHERE task=? AND stage=? AND attempt=?",
                (claim["task"], claim["stage"], claim["attempt"]),
            ).fetchone()
            reservation = max(attempt[0], until - claim["started"])
            if used - attempt[0] + reservation > 600:
                raise ValueError("Renewal exceeds the persisted external wall allowance")
            changed = self.registry.db.execute(
                "UPDATE role_tasks SET lease_until=? WHERE id=? AND owner=? AND lease_until>=?",
                (until, claim["task"], "actor:" + claim_id, now),
            ).rowcount
            if not changed:
                raise ValueError("Task ownership changed before renewal")
            self.registry.db.execute(
                "UPDATE actor_claims SET lease_until=? WHERE id=?", (until, claim_id)
            )
            self.registry.db.execute(
                "UPDATE role_attempts SET wall_reserved=? WHERE task=? AND stage=? AND attempt=?",
                (reservation, claim["task"], claim["stage"], claim["attempt"]),
            )
            self._charge(actor, len(json.dumps(result).encode()))
            self.auth(token, claim["task"])
        return result

    def answer(self, token: str, response: ActorAnswer) -> dict[str, Any]:
        actor = self.auth(token)
        claim = self._claim(actor, response.claim)
        self.auth(token, claim["task"])
        digest = fingerprint(response.answer)
        if claim["response_sha"] is not None:
            with self.registry.transaction():
                self.auth(token, claim["task"])
                return self._answered(actor, claim, digest)
        task = self.worker.get(claim["task"])
        self.worker._current(task)
        role, packet = self.worker._packet(task)
        if (
            task["stage"] != claim["stage"]
            or fingerprint(packet) != claim["packet_sha"]
            or task["context"]["contract"] != VERSION
        ):
            raise ValueError("Frozen stage/capability changed; no external answer dispatch")
        raw = json.dumps(response.answer, sort_keys=True, allow_nan=False)
        if len(raw.encode()) > 8192:
            raise ValueError("External answer exceeds eight KiB")
        result = {
            "task": claim["task"],
            "answer_sha256": digest,
            "status": "recorded",
            "next": "Existing worker evaluates and requires local review; no funding here",
        }
        error = None
        try:
            validate(role, response.answer, packet)
        except ValueError as exc:
            error = str(exc)[:300]
        with self.registry.transaction():
            actor = self.auth(token, claim["task"])
            claim = self._claim(actor, response.claim)
            if claim["response_sha"] is not None:
                return self._answered(actor, claim, digest)
            if claim["status"] != "claimed" or claim["lease_until"] < time.time():
                raise ValueError("External claim expired or released; no effect")
            changed = self.registry.db.execute(
                "UPDATE role_tasks SET owner=NULL,lease_until=NULL,status=?,reason=? "
                "WHERE id=? AND stage=? AND owner=? AND lease_until>=?",
                (
                    "failed" if error else "queued",
                    error,
                    claim["task"],
                    claim["stage"],
                    "actor:" + response.claim,
                    time.time(),
                ),
            ).rowcount
            if not changed:
                raise ValueError("External claim expired or ownership changed; no effect")
            self.registry.db.execute(
                "UPDATE role_attempts SET response=?,finished=?,status=?,reason=? "
                "WHERE task=? AND stage=? AND attempt=?",
                (
                    json.dumps(
                        {
                            "answer": response.answer,
                            "actor": actor["actor"],
                            "scope": "External final output; no private reasoning retained",
                        }
                    ),
                    time.time(),
                    "failed" if error else "answered",
                    error,
                    claim["task"],
                    claim["stage"],
                    claim["attempt"],
                ),
            )
            self.registry.db.execute(
                "UPDATE actor_claims SET response_sha=?,status='answered' WHERE id=?",
                (digest, response.claim),
            )
            self._charge(actor, len(json.dumps(result).encode()))
            self.auth(token, claim["task"])
        if error:
            raise ValueError("Non-executable external answer retained: " + error)
        return result

    def _answered(
        self, actor: dict[str, Any], claim: dict[str, Any], digest: str
    ) -> dict[str, Any]:
        if claim["response_sha"] != digest:
            raise ValueError("Completed external answer cannot be rewritten")
        result = {"task": claim["task"], "answer_sha256": digest, "status": "already_recorded"}
        self._charge(actor, len(json.dumps(result).encode()))
        # The debit checks current expiry/revocation inside the owning transaction.
        return result

    def _release(self, claim: dict[str, Any], reason: str) -> None:
        self.registry.db.execute(
            "UPDATE role_tasks SET owner=NULL,lease_until=NULL,status='failed',reason=? "
            "WHERE id=? AND owner=?",
            (reason, claim["task"], "actor:" + claim["id"]),
        )
        self.registry.db.execute(
            "UPDATE role_attempts SET status='failed',reason=?,finished=? "
            "WHERE task=? AND stage=? AND attempt=? AND response IS NULL",
            (reason, time.time(), claim["task"], claim["stage"], claim["attempt"]),
        )
        self.registry.db.execute(
            "UPDATE actor_claims SET status='released' WHERE id=?", (claim["id"],)
        )

    def release(self, token: str, claim_id: str) -> None:
        with self.registry.transaction():
            actor = self.auth(token)
            claim = self._claim(actor, claim_id)
            self.auth(token, claim["task"])
            self._charge(actor, 0)
            if claim["status"] == "claimed":
                self._release(
                    claim, "External claim released; completion unknown, explicit retry required"
                )
            self.auth(token, claim["task"])

    def result(self, token: str, task_id: str) -> dict[str, Any]:
        actor = self.auth(token, task_id)
        task = self.worker.view(task_id)
        result = {k: task[k] for k in ("id", "stage", "status", "reason", "result", "updated")}
        result["scope"] = "Granted task result only; outcome disclosure recorded before delivery"
        encoded = json.dumps(result, allow_nan=False)
        self._charge(actor, len(encoded.encode()))
        return result

    def maintenance(self, token: str) -> dict[str, Any]:
        actor = self.auth(token)
        status = storage_snapshot(self.registry.path.parent)
        result = {
            "storage_state": status.get("state", "unknown"),
            "tasks": [
                {key: self.worker.get(identity)[key] for key in ("id", "stage", "status")}
                for identity in actor["scope"]["tasks"]
            ],
            "action": (
                "Inspect only; existing local maintenance owns migration/expiry. "
                "Propose follow-up within a granted task."
            ),
            "authority": "No delete, policy, funding, filesystem or training-weight capability",
        }
        self._charge(actor, len(json.dumps(result).encode()))
        return result
