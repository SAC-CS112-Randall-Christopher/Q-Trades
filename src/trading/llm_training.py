"""Reviewed, offline role-training data; never a model or financial authority.

Exports are unreviewed. Explicit semantic adjudication establishes target correctness, rights,
point-in-time source availability and episode-family membership. Hashes detect
accidental changes; they are not signatures or proof that an assertion is true.
"""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading.experiment_registry import fingerprint
from trading.lab_role_contract import VERSION, contract_hash, packet_json, prompt, validate

FORMAT = "qtrades-role-training-v1"
MAX_ROW_BYTES = 262_144
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_ROWS = 2_000
SPLITS = ("train", "validation", "test")


class Checked(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class InstructionalAuthorship(Checked):
    author: str = Field(min_length=3, max_length=120)
    authored_at: float = Field(ge=0)
    rights_basis: str = Field(min_length=20, max_length=1000)
    original_draft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    empirical_performance_claim: Literal[False]


class ObservedSource(Checked):
    kind: Literal["numerical_experiment", "market_observation"]
    identity: str = Field(min_length=8, max_length=100)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_start: float = Field(ge=0)
    observed_end: float = Field(ge=0)
    available_at: float = Field(ge=0)
    evidence_basis: Literal["observed_public_quotes", "synthetic_qa"]
    supported_claims: list[Literal["interpretation"]] = Field(min_length=1, max_length=1)
    original_question: None
    original_model_answer: None
    original_record: dict[str, Any] | None = Field(default=None, exclude_if=lambda v: v is None)


class Candidate(Checked):
    format: Literal["qtrades-role-training-v1"]
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["researcher", "reviewer"]
    stage: Literal["idea", "review", "followup"]
    task_id: str = Field(min_length=1, max_length=100)
    attempt: int = Field(ge=0, le=100)
    source_kind: Literal["model_attempt", "instructional", "observed_episode"] = Field(
        default="model_attempt", exclude_if=lambda v: v == "model_attempt"
    )
    authorship: InstructionalAuthorship | None = Field(default=None, exclude_if=lambda v: v is None)
    observed_source: ObservedSource | None = Field(default=None, exclude_if=lambda v: v is None)
    decision_at: float = Field(ge=0)
    finished_at: float = Field(ge=0)
    group_ids: list[str] = Field(min_length=1, max_length=32)
    packet: dict[str, Any]
    original_answer: Any
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def intact(self) -> Self:
        from trading.account_purpose import require_research_provenance

        require_research_provenance(self.packet)
        if self.observed_source is not None:
            require_research_provenance(self.observed_source.original_record)
        if self.source_kind == "instructional":
            if (
                self.authorship is None
                or self.attempt != 0
                or self.original_answer is not None
                or not self.task_id.startswith("authored:")
                or self.decision_at != self.finished_at
                or self.decision_at != self.authorship.authored_at
            ):
                raise ValueError(
                    "Instructional authorship must not imitate a completed model attempt"
                )
        elif self.source_kind == "observed_episode":
            source = self.observed_source
            if (
                source is None
                or self.authorship is None
                or self.attempt != 0
                or self.original_answer is not None
                or not self.task_id.startswith("episode:")
                or self.decision_at != self.authorship.authored_at
                or self.finished_at != self.decision_at
                or not source.observed_start <= source.observed_end <= source.available_at
                or source.available_at > self.decision_at
            ):
                raise ValueError("Retain observation and authored-question times separately")
            if source.original_record is not None and (
                fingerprint(source.original_record) != source.source_sha256
            ):
                raise ValueError("Original retained observation changed")
        elif self.attempt < 1 or self.authorship is not None:
            raise ValueError("Model examples require their retained completed attempt")
        if self.source_kind != "observed_episode" and self.observed_source is not None:
            raise ValueError("Only an observed episode carries observed-source metadata")
        if self.contract_sha256 != contract_hash():
            raise ValueError("Stale role contract; do not silently relabel its examples")
        if (self.stage == "review") != (self.role == "reviewer"):
            raise ValueError("Stage and role disagree")
        if self.finished_at < self.decision_at:
            raise ValueError("Completion precedes the decision")
        if self.packet_sha256 != fingerprint(self.packet):
            raise ValueError("Original packet changed")
        body = self.model_dump(exclude={"candidate_sha256"})
        if self.candidate_sha256 != fingerprint(body):
            raise ValueError("Candidate changed; keep original evidence and use a reviewed target")
        if not isinstance(self.packet.get("evidence"), dict) or not self.packet["evidence"]:
            raise ValueError("A candidate requires its exact evidence packet")
        if not isinstance(self.packet.get("capabilities"), dict):
            raise ValueError("A candidate requires its original capability catalog")
        if not isinstance(self.packet.get("question"), str):
            raise ValueError("A candidate requires its original question")
        if len(packet_json(self.packet).encode()) > 131_072:
            raise ValueError("Packet exceeds the role evidence limit")
        return self


class Approval(Checked):
    approved: Literal[True]
    reviewer: str = Field(min_length=3, max_length=120)
    reviewed_at: float = Field(ge=0)
    rationale: str = Field(min_length=20, max_length=2000)
    rights_confirmed: Literal[True]
    data_basis: Literal[
        "instructional", "synthetic", "observed", "historical_replay", "prospective"
    ]
    reviewer_kind: Literal["human", "delegated_semantic"]
    reviewer_authored_material: bool
    family_ids: list[str] = Field(min_length=1, max_length=32)
    categories: list[str] = Field(min_length=1, max_length=12)
    episode_start: float = Field(ge=0)
    episode_end: float = Field(ge=0)
    target_available_at: float = Field(ge=0)
    evidence_available_at: dict[str, float]
    claim_scope: Literal["interpretation", "price_path", "original_execution", "counterfactual"]


class Example(Checked):
    candidate: Candidate
    review: Approval
    target: dict[str, Any]

    @model_validator(mode="after")
    def supported(self) -> Self:
        c, r = self.candidate, self.review
        if c.source_kind == "instructional" and r.data_basis != "instructional":
            raise ValueError("Keep authored instruction separate from empirical/model episodes")
        if c.source_kind == "model_attempt" and r.data_basis == "instructional":
            raise ValueError("Do not relabel an original model attempt authored instruction")
        if c.source_kind == "observed_episode":
            source = c.observed_source
            assert source is not None
            basis = "synthetic" if source.evidence_basis == "synthetic_qa" else "observed"
            if r.data_basis != basis or r.claim_scope not in source.supported_claims:
                raise ValueError(
                    "This retained episode supports interpretation, not execution claims"
                )
            if (r.episode_start, r.episode_end) != (source.observed_start, source.observed_end):
                raise ValueError("Keep the original observed interval")
            if any(t < source.available_at for t in r.evidence_available_at.values()):
                raise ValueError("Do not backdate observed receipt availability")
        if r.reviewer_kind == "delegated_semantic" and not (
            c.source_kind == "instructional"
            or (c.source_kind == "observed_episode" and r.claim_scope == "interpretation")
        ):
            raise ValueError("Delegated instructional review cannot approve empirical episodes")
        if r.reviewed_at < c.finished_at:
            raise ValueError("Review must follow the retained attempt")
        if not (r.episode_start <= r.episode_end <= c.decision_at):
            raise ValueError("Declare the causal episode window, not a future interval")
        if r.target_available_at > c.decision_at:
            raise ValueError("Target relies on future facts absent at this decision")
        if set(r.evidence_available_at) != set(c.packet["evidence"]):
            raise ValueError("Review source availability for every supplied evidence handle")
        if any(not 0 <= t <= c.decision_at for t in r.evidence_available_at.values()):
            raise ValueError("Evidence was not available at the decision cutoff")
        if any(not x.strip() or len(x) > 200 for x in r.family_ids + r.categories + c.group_ids):
            raise ValueError("Use nonempty bounded family and category identifiers")
        validate(c.role, self.target, c.packet)
        return self


def candidate_from_instruction(
    *,
    identity: str,
    role: str,
    packet: dict[str, Any],
    authored_at: float,
    author: str,
    rights_basis: str,
    draft_sha256: str,
    family_ids: list[str],
) -> dict[str, Any]:
    """Freeze an authored nonempirical question, never fabricate an operating episode.

    All target facts still must exist at authorship. A claim about measured trading
    performance must instead use its genuinely completed empirical episode.
    """
    candidate = {
        "format": FORMAT,
        "contract_sha256": contract_hash(),
        "role": role,
        "stage": "review" if role == "reviewer" else "idea",
        "task_id": "authored:" + identity,
        "attempt": 0,
        "source_kind": "instructional",
        "authorship": {
            "author": author,
            "authored_at": authored_at,
            "rights_basis": rights_basis,
            "original_draft_sha256": draft_sha256,
            "empirical_performance_claim": False,
        },
        "decision_at": authored_at,
        "finished_at": authored_at,
        "group_ids": family_ids,
        "packet": packet,
        "original_answer": None,
        "packet_sha256": fingerprint(packet),
    }
    candidate["candidate_sha256"] = fingerprint(candidate)
    return Candidate.model_validate(candidate).model_dump()


def candidate_from_task(task: dict[str, Any], stage: str, attempt: int) -> dict[str, Any]:
    """Use the retained request, never regenerate today's packet for an old answer."""
    from trading.account_purpose import require_research_provenance

    require_research_provenance(task.get("context"))
    if stage not in {"idea", "review", "followup"}:
        raise ValueError("Select an actual model-attempt stage")
    if task["context"]["contract"] != VERSION:
        raise ValueError("This historical task has a different role contract")
    matches = [a for a in task["attempts"] if a["stage"] == stage and a["attempt"] == attempt]
    if len(matches) != 1:
        raise ValueError("Selected retained model attempt is unavailable")
    row = matches[0]
    if row["finished"] is None or row["response"] is None:
        raise ValueError("No completed answer; a timeout is not a training target")
    packet = json.loads(row["packet"]) if isinstance(row["packet"], str) else row["packet"]
    response = json.loads(row["response"]) if isinstance(row["response"], str) else row["response"]
    if not isinstance(response, dict) or "answer" not in response:
        raise ValueError("Retained final answer is unavailable")
    groups = ["task:" + task["id"]]
    question = task["context"]["question"]
    if question.get("parent"):
        groups.append("parent:" + question["parent"])
    issued = task["context"].get("issued", {})
    if issued.get("sha256"):
        groups.append("bundle:" + issued["sha256"])
    body = {
        "format": FORMAT,
        "contract_sha256": contract_hash(),
        "role": "reviewer" if stage == "review" else "researcher",
        "stage": stage,
        "task_id": task["id"],
        "attempt": attempt,
        "decision_at": float(row["started"]),
        "finished_at": float(row["finished"]),
        "group_ids": groups,
        "packet": packet,
        "original_answer": response["answer"],
        "packet_sha256": fingerprint(packet),
    }
    candidate = Candidate.model_validate(body | {"candidate_sha256": fingerprint(body)})
    result = {
        "candidate": candidate.model_dump(),
        "review": None,
        "target": None,
        "instructions": "Unreviewed private candidate, NOT training data. Preserve candidate; "
        "supply an explicit reviewed target and Approval metadata using the offline pilot. "
        "Include every related episode/parent family and verify all source availability. "
        "No inference, strategy approval or weight update follows from this export.",
    }
    if len(packet_json(result).encode()) > MAX_ROW_BYTES:
        raise ValueError("Candidate exceeds export limit; original attempt remains retained")
    return result


def candidate_from_episode(
    record: dict[str, Any], *, question: str, role: str, author: str, authored_at: float
) -> dict[str, Any]:
    """Teach interpretation of an original result, without inventing historical intent."""
    from trading.account_purpose import require_research_provenance

    require_research_provenance(record)
    if record["status"] not in {"completed", "failed", "rejected", "cancelled"}:
        raise ValueError("Episode is not a retained terminal observation")
    finished = record.get("finished")
    if finished is None:
        raise ValueError("Original receipt availability is unknown")
    plan = record["plan"]
    original = {
        k: record.get(k)
        for k in (
            "request_id",
            "plan",
            "plan_sha256",
            "code_sha256",
            "created",
            "finished",
            "status",
            "snapshot_sha256",
            "result",
            "result_sha256",
            "reason",
        )
    }
    source_sha = fingerprint(original)
    packet = {
        "question": question,
        "capabilities": {},
        "evidence": {"e0": original},
        "scope": "Retained numerical episode; interpretation only. No original model answer. "
        "Computed results are not original fills or verified executable returns.",
    }
    body = {
        "format": FORMAT,
        "contract_sha256": contract_hash(),
        "role": role,
        "stage": "review" if role == "reviewer" else "idea",
        "task_id": "episode:" + record["request_id"],
        "attempt": 0,
        "source_kind": "observed_episode",
        "decision_at": authored_at,
        "finished_at": authored_at,
        "original_answer": None,
        "authorship": {
            "author": author,
            "authored_at": authored_at,
            "rights_basis": "Authored question only; source-data rights remain unresolved "
            "until explicit review of the original provider and retained result.",
            "original_draft_sha256": fingerprint({"question": question, "role": role}),
            "empirical_performance_claim": False,
        },
        "observed_source": {
            "kind": "numerical_experiment",
            "identity": record["request_id"],
            "source_sha256": source_sha,
            "observed_start": plan["test_start"],
            "observed_end": plan["test_end"],
            "available_at": float(finished),
            "evidence_basis": plan["evidence_kind"],
            "supported_claims": ["interpretation"],
            "original_question": None,
            "original_model_answer": None,
            "original_record": original,
        },
        "group_ids": [
            "episode:" + record["request_id"],
            "source:" + source_sha,
            "market-window:" + fingerprint([plan["test_start"], plan["test_end"]]),
        ],
        "packet": packet,
        "packet_sha256": fingerprint(packet),
    }
    body["candidate_sha256"] = fingerprint(body)
    return Candidate.model_validate(body).model_dump()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Bound reads before allocation; reject malformed/nonfinite input without dropping rows."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Use a regular JSONL input no larger than 64 MiB")
    rows: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        while raw := stream.readline(MAX_ROW_BYTES + 1):
            if len(raw) > MAX_ROW_BYTES or len(rows) >= MAX_ROWS:
                raise ValueError("Input row/count limit exceeded; nothing was silently truncated")
            try:
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError("Expected a JSON object")
                packet_json(row)  # Disallow NaN/infinity anywhere, including evidence.
            except (ValueError, TypeError, UnicodeDecodeError) as exc:
                raise ValueError(f"Invalid JSONL row {len(rows) + 1}") from exc
            rows.append(row)
    return rows


def _values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for key in sorted(value) for text in _values(value[key])]
    if isinstance(value, list):
        return [text for item in value for text in _values(item)]
    return [str(value)]


def _content(packet: dict[str, Any]) -> str:
    # Ignore opaque evidence keys; renaming e0 must not evade duplicate protection.
    return " ".join(re.findall(r"\w+", " ".join(_values(packet["evidence"])).casefold()))


def _grams(text: str) -> set[str]:
    words = text.split()
    return {" ".join(words[i : i + 5]) for i in range(max(1, len(words) - 4))}


def candidate_from_market(
    record: dict[str, Any], *, question: str, role: str, author: str, authored_at: float
) -> dict[str, Any]:
    """The retained raw public response has a receipt time, not an executable fill."""
    from datetime import datetime

    available = datetime.fromisoformat(record["observed_at"]).timestamp()
    if available > authored_at or record["kind"] != "depth":
        raise ValueError("Select an original received depth observation")
    original = {
        k: record[k] for k in ("id", "kind", "symbol", "observed_at", "payload", "config_hash")
    }
    source_sha = fingerprint(original)
    evidence = {k: v for k, v in original.items() if k != "payload"}
    evidence["raw_response_sha256"] = fingerprint(record["payload"])
    evidence["exchange_event_time"] = None
    evidence["engine_eligibility"] = None
    evidence["training_projection"] = (
        "Original local receipt/identity metadata only; raw prices/depth excluded"
    )
    packet = {
        "question": question,
        "capabilities": {},
        "evidence": {"e0": evidence},
        "scope": "Original Binance.US public depth response. observed_at is local receipt "
        "time; exchange event time/clock uncertainty and engine eligibility are unknown. "
        "No original LLM question, fill, execution or return claim.",
    }
    body = candidate_from_instruction(
        identity="market-" + source_sha[:20],
        role=role,
        packet=packet,
        authored_at=authored_at,
        author=author,
        rights_basis="Authored question; source usage rights require explicit review.",
        draft_sha256=fingerprint({"question": question, "role": role}),
        family_ids=["observation:" + source_sha, f"market-minute:{int(available // 60)}"],
    )
    body.update(
        source_kind="observed_episode",
        task_id="episode:market-" + source_sha[:20],
        observed_source={
            "kind": "market_observation",
            "identity": "market-" + source_sha[:20],
            "source_sha256": source_sha,
            "observed_start": available,
            "observed_end": available,
            "available_at": available,
            "evidence_basis": "observed_public_quotes",
            "supported_claims": ["interpretation"],
            "original_question": None,
            "original_model_answer": None,
            "original_record": original,
        },
    )
    body["candidate_sha256"] = fingerprint(
        {k: v for k, v in body.items() if k != "candidate_sha256"}
    )
    Candidate.model_validate(body)
    return {"candidate": body, "review": None, "target": None}


def exposure_metadata(example: Example) -> dict[str, Any]:
    """Metadata only: the Lab owns historical use; no evaluation answer is needed."""
    c, r = example.candidate, example.review
    evidence_key = fingerprint(_content(c.packet))
    return {
        "id": c.candidate_sha256,
        "source_kind": c.source_kind,
        "data_basis": r.data_basis,
        "evidence_key": evidence_key,
        "task_key": fingerprint(
            [c.role, " ".join(c.packet["question"].split()), c.packet["capabilities"], evidence_key]
        ),
        "families": sorted(set(c.group_ids + ["family:" + f for f in r.family_ids])),
        "window": [r.episode_start, r.episode_end] if c.source_kind != "instructional" else None,
        "categories": r.categories,
        "role": c.role,
    }


def prepare(
    rows: list[dict[str, Any]],
    *,
    train_end: float,
    validation_end: float,
    embargo_seconds: float,
    protected_packets: list[dict[str, Any]],
    preparation_only: bool = False,
) -> dict[str, Any]:
    """Freeze a reviewed corpus; refuse cross-family leakage rather than random-split rows."""
    if not all(math.isfinite(v) for v in (train_end, validation_end, embargo_seconds)):
        raise ValueError("Cutoffs and embargo must be finite")
    if not 0 <= train_end < validation_end or embargo_seconds < 0:
        raise ValueError("Require ordered cutoffs and a nonnegative embargo")
    if not 1 <= len(rows) <= MAX_ROWS or not protected_packets:
        raise ValueError("Require bounded reviewed examples and protected evaluation packets")
    from trading.llm_training_preflight import preflight

    report = preflight(
        rows,
        train_end=train_end,
        validation_end=validation_end,
        embargo_seconds=embargo_seconds,
        protected_packets=protected_packets,
        preparation_only=preparation_only,
    )
    if not report["eligible"]:
        raise ValueError(
            "Corpus preflight failed: "
            + "; ".join(f"{p['id']}: {p['code']}: {p['reason']}" for p in report["problems"])[:6000]
        )
    protected = [_content(p) for p in protected_packets]
    protected_grams = [_grams(p) for p in protected]
    files: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}
    provenance: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}
    groups: dict[str, str] = {}
    seen: set[str] = set()
    content_splits: dict[str, str] = {}
    prior_grams: list[tuple[str, set[str]]] = []
    task_targets: dict[str, str] = {}
    metadata: dict[str, dict[str, Any]] = {}
    examples = [Example.model_validate(row) for row in rows]
    examples.sort(key=lambda e: (e.candidate.decision_at, e.candidate.candidate_sha256))
    for example in examples:
        c, r = example.candidate, example.review
        identity = c.candidate_sha256
        if identity in seen:
            raise ValueError("Duplicate candidate; repetitions are not independent examples")
        seen.add(identity)
        if c.decision_at <= train_end:
            split = "train"
        elif r.episode_start > train_end + embargo_seconds and c.decision_at <= validation_end:
            split = "validation"
        elif r.episode_start > validation_end + embargo_seconds:
            split = "test"
        else:
            raise ValueError("Episode crosses a cutoff/embargo; review the declared split")
        text = _content(c.packet)
        grams = _grams(text)
        if any(text == p for p in protected) or any(
            len(g) >= 8 and len(grams & g) / len(g) >= 0.85 for g in protected_grams
        ):
            raise ValueError("Protected qualification evidence cannot enter the pilot corpus")
        if text in content_splits and content_splits[text] != split:
            raise ValueError("Duplicate evidence crosses evaluation splits")
        meta = exposure_metadata(example) | {"split": split}
        task_key = meta["task_key"]
        if task_key in task_targets:
            if task_targets[task_key] != fingerprint(example.target):
                raise ValueError("Conflicting targets for the same task and evidence")
            raise ValueError(
                "Duplicate task; shared evidence with different questions is permitted"
            )
        if any(
            previous_split != split
            and min(len(g), len(grams)) >= 8
            and len(grams & g) / min(len(g), len(grams)) >= 0.85
            for previous_split, g in prior_grams
        ):
            raise ValueError("Near-copy evidence crosses evaluation splits")
        content_splits[text] = split
        task_targets[task_key] = fingerprint(example.target)
        metadata[identity] = meta
        prior_grams.append((split, grams))
        for group in c.group_ids + ["family:" + f for f in r.family_ids]:
            if group in groups and groups[group] != split:
                raise ValueError("Related task/parent/episode family crosses evaluation splits")
            groups[group] = split
        files[split].append(
            {
                "id": identity,
                "role": c.role,
                "prompt": [
                    {"role": "system", "content": prompt(c.role)},
                    {"role": "user", "content": packet_json(c.packet)},
                ],
                "completion": [{"role": "assistant", "content": packet_json(example.target)}],
            }
        )
        provenance[split].append(example.model_dump())
    if not preparation_only and any(not files[s] for s in SPLITS):
        raise ValueError("All three chronological splits require reviewed examples")
    if preparation_only and (not files["train"] or files["validation"] or files["test"]):
        raise ValueError("Preparation-only export must contain training material only")
    return {
        "files": files,
        "provenance": provenance,
        "manifest": {
            "format": FORMAT,
            "purpose": "training_preparation" if preparation_only else "training_and_evaluation",
            "exposure_metadata": metadata,
            "contract_sha256": contract_hash(),
            "train_end": train_end,
            "validation_end": validation_end,
            "embargo_seconds": embargo_seconds,
            "protected_packets_sha256": fingerprint(protected_packets),
            "counts": {s: len(files[s]) for s in SPLITS},
            "roles": {s: dict(Counter(e["role"] for e in files[s])) for s in SPLITS},
            "categories": {
                s: dict(Counter(k for e in provenance[s] for k in e["review"]["categories"]))
                for s in SPLITS
            },
            "data_basis": dict(Counter(e.review.data_basis for e in examples)),
            "limitations": [
                "Recorded semantic reviewer attests facts/rights/families; "
                "hashes are not proof of truth.",
                "Exact/near-copy exclusions cannot prove semantic or pretrained-data independence.",
                "Public procedural fixtures are not blind qualification or trading evidence.",
                "No training, role qualification, activation or financial permission is implied.",
            ],
        },
    }


def write_bundle(bundle: dict[str, Any], destination: Path) -> dict[str, Any]:
    destination = destination.resolve()
    if any((p / ".git").exists() for p in (destination, *destination.parents)):
        raise ValueError("Keep training data outside source repositories")
    payloads: dict[str, bytes] = {}
    for split in SPLITS:
        for suffix, source in [("", "files"), (".provenance", "provenance")]:
            payloads[split + suffix + ".jsonl"] = "".join(
                packet_json(r) + "\n" for r in bundle[source][split]
            ).encode()
    if any(len(body) > MAX_INPUT_BYTES for body in payloads.values()):
        raise ValueError("Expanded export exceeds the file limit; reduce the reviewed corpus")
    manifest = bundle["manifest"] | {
        "files": {
            name: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            for name, body in payloads.items()
        }
    }
    manifest["corpus_sha256"] = fingerprint(manifest)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    # Write the manifest last. Interrupted exports stay visibly incomplete; no overwrite/retry.
    for name, body in payloads.items():
        with (destination / name).open("xb") as stream:
            stream.write(body)
    with (destination / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(packet_json(manifest) + "\n")
    return dict(manifest)


def verify_bundle(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 131_072:
        raise ValueError("Missing or invalid completion manifest; export may be interrupted")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    digest = manifest.pop("corpus_sha256", None)
    if digest != fingerprint(manifest) or manifest.get("contract_sha256") != contract_hash():
        raise ValueError("Changed corpus manifest or stale contract")
    expected = {s + suffix + ".jsonl" for s in SPLITS for suffix in ("", ".provenance")}
    if set(manifest.get("files", {})) != expected:
        raise ValueError("Unexpected corpus file membership")
    for name, meta in manifest["files"].items():
        file = directory / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("Missing, linked or oversized corpus file")
        body = file.read_bytes()
        if len(body) != meta["bytes"] or hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise ValueError("Corpus file changed after its split was frozen")
    return dict(manifest) | {"corpus_sha256": digest}
