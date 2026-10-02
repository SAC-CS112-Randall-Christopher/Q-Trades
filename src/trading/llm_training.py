"""Reviewed, offline role-training data; never a model or financial authority.

Exports are unreviewed. Human adjudication establishes target correctness, rights,
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


class Candidate(Checked):
    format: Literal["qtrades-role-training-v1"]
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["researcher", "reviewer"]
    stage: Literal["idea", "review", "followup"]
    task_id: str = Field(min_length=1, max_length=100)
    attempt: int = Field(ge=1, le=100)
    decision_at: float = Field(ge=0)
    finished_at: float = Field(ge=0)
    group_ids: list[str] = Field(min_length=1, max_length=32)
    packet: dict[str, Any]
    original_answer: Any
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def intact(self) -> Self:
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
    data_basis: Literal["synthetic", "observed"]
    family_ids: list[str] = Field(min_length=1, max_length=32)
    categories: list[str] = Field(min_length=1, max_length=12)
    episode_start: float = Field(ge=0)
    episode_end: float = Field(ge=0)
    target_available_at: float = Field(ge=0)
    evidence_available_at: dict[str, float]


class Example(Checked):
    candidate: Candidate
    review: Approval
    target: dict[str, Any]

    @model_validator(mode="after")
    def supported(self) -> Self:
        c, r = self.candidate, self.review
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


def candidate_from_task(task: dict[str, Any], stage: str, attempt: int) -> dict[str, Any]:
    """Use the retained request, never regenerate today's packet for an old answer."""
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


def prepare(
    rows: list[dict[str, Any]],
    *,
    train_end: float,
    validation_end: float,
    embargo_seconds: float,
    protected_packets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Freeze a reviewed corpus; refuse cross-family leakage rather than random-split rows."""
    if not all(math.isfinite(v) for v in (train_end, validation_end, embargo_seconds)):
        raise ValueError("Cutoffs and embargo must be finite")
    if not 0 <= train_end < validation_end or embargo_seconds < 0:
        raise ValueError("Require ordered cutoffs and a nonnegative embargo")
    if not 1 <= len(rows) <= MAX_ROWS or not protected_packets:
        raise ValueError("Require bounded reviewed examples and protected evaluation packets")
    protected = [_content(p) for p in protected_packets]
    protected_grams = [_grams(p) for p in protected]
    files: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}
    provenance: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}
    groups: dict[str, str] = {}
    seen: set[str] = set()
    content_splits: dict[str, str] = {}
    prior_grams: list[tuple[str, set[str]]] = []
    role_contents: set[tuple[str, str]] = set()
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
        if (c.role, text) in role_contents:
            raise ValueError("Repeated role/evidence example would overweight the same experience")
        if any(
            previous_split != split
            and min(len(g), len(grams)) >= 8
            and len(grams & g) / min(len(g), len(grams)) >= 0.85
            for previous_split, g in prior_grams
        ):
            raise ValueError("Near-copy evidence crosses evaluation splits")
        content_splits[text] = split
        role_contents.add((c.role, text))
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
    if any(not files[s] for s in SPLITS):
        raise ValueError("All three chronological splits require reviewed examples")
    return {
        "files": files,
        "provenance": provenance,
        "manifest": {
            "format": FORMAT,
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
                "Human review attests facts/rights/families; hashes are not proof of truth.",
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
