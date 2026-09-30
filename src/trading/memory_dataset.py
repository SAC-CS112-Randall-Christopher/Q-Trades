"""Bounded corpus from existing immutable episodes and same-engine filled-trade evidence."""

import json
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.execution_replay import (
    balanced,
    checked_packet,
    hydrated_frames,
    ordered_state,
    source_hashes,
)
from trading.paper_engine import PaperEngine
from trading.research_evidence import digest


def executable_label(
    descriptor: dict[str, Any],
    records: list[dict[str, Any]],
    as_of: float,
    verified: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    unavailable: dict[str, Any] = {
        "status": "unavailable",
        "version": "executed-trade-net-v1",
        "horizon_seconds": 2700,
        "net_bps": None,
        "reason": "No complete linked same-engine filled trade and matured horizon",
    }
    if descriptor.get("status") != "available" or as_of < descriptor["horizon_at"]:
        return dict(unavailable, status="pending")
    source = source_hashes()
    entries: dict[tuple[str, float], dict[str, Any]] = {}
    chosen = None
    outcome = None
    verified = {} if verified is None else verified
    for record in records:
        if record["payload"]["at"] > as_of:
            continue
        packet = verified.get(record["sha256"])
        if packet is None:
            try:
                packet = checked_packet(record, source)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                return dict(unavailable, reason="Source inputs cannot be reproduced")
            try:
                engine = PaperEngine(ordered_state(packet), packet["at"])
                engine.tick(hydrated_frames(packet), packet["study"])
            except (ValueError, KeyError, TypeError, ArithmeticError):
                return dict(unavailable, reason="Isolated source state cannot be reproduced")
            if (
                digest(engine.state) != packet["after_tick_sha256"]
                or engine.events != packet["events"]
                or not balanced(engine.events)
            ):
                return dict(unavailable, reason="Source replay reconciliation failed")
            verified[record["sha256"]] = packet
        committed = (packet.get("financial_commit") or {}).get("committed_at", packet["at"])
        if committed > as_of:
            continue
        for event in packet["events"]:
            b = event["body"]
            if (
                event["kind"] == "order_intent"
                and b["side"] == "buy"
                and b["symbol"] == "BTCUSD"
                and b["version"] == "breakout-v1"
                and b["created_at"] == descriptor["cutoff"]
                and chosen is None
            ):
                chosen = (event["account"], None)
            if event["kind"] == "fill" and b["side"] == "buy" and b["symbol"] == "BTCUSD":
                # Link the intent's prefix, never a later profitable trade selected by outcome.
                if b["created_at"] == descriptor["cutoff"] and chosen == (event["account"], None):
                    chosen = (event["account"], packet["at"])
                    entries[(event["account"], packet["at"])] = {
                        "record": record["id"],
                        "sha256": record["sha256"],
                        "body": b,
                    }
            if event["kind"] == "trade_closed" and b["symbol"] == "BTCUSD":
                entry = entries.get((event["account"], b["opened_at"]))
                if (
                    entry
                    and (event["account"], b["opened_at"]) == chosen
                    and b["closed_at"] <= descriptor["horizon_at"]
                ):
                    pnl, cost, proceeds = (Decimal(str(b[k])) for k in ("pnl", "cost", "proceeds"))
                    if (
                        not all(x.is_finite() for x in (pnl, cost, proceeds))
                        or cost <= 0
                        or pnl != proceeds - cost
                    ):
                        return dict(unavailable, reason="Net trade target does not reconcile")
                    # First dispatch-account entry is fixed before outcomes; clones add no labels.
                    outcome = {
                        "status": "available",
                        "version": "executed-trade-net-v1",
                        "horizon_seconds": 2700,
                        "available_at": None,
                        "net_bps": float(pnl / cost * 10000),
                        "fees_embedded_once": True,
                        "entry": entry,
                        "exit": {"record": record["id"], "sha256": record["sha256"], "body": b},
                        "account": event["account"],
                        "data_mode": descriptor["data_mode"],
                        "coverage": "Modeled paper fills; unexecuted counterfactuals stay unknown",
                    }
        if outcome and packet["at"] >= descriptor["horizon_at"]:
            outcome["available_at"] = max(packet["at"], committed)
            outcome["maturity_reference"] = {"record": record["id"], "sha256": record["sha256"]}
            return outcome
    return unavailable


def corpus_snapshot(path: Path, as_of: float) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("Durable episode archive is unavailable")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        episodes = db.execute(
            "SELECT * FROM evidence_episodes WHERE cutoff<=? AND available_at<=? "
            "ORDER BY cutoff,episode",
            (as_of, as_of),
        ).fetchall()
        if len(episodes) > 512:
            raise ValueError("Declared corpus exceeds 512 retained episodes")
        rows = []
        for episode in episodes:
            d = json.loads(episode["descriptor"])
            if digest(d) != episode["descriptor_sha256"]:
                raise ValueError("Retained descriptor changed")
            # Freeze raw dependencies, not price-only outcomes pretending to be net labels.
            rows.append(
                {
                    "episode": episode["episode"],
                    "record_id": episode["record_id"],
                    "available_at": episode["available_at"],
                    "descriptor": d,
                    "executable_label": None,
                }
            )
        count, total = db.execute(
            "SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) "
            "FROM evidence_records WHERE kind='decision' AND at<=?",
            (as_of,),
        ).fetchone()
        if total > 8 * 1024**2:
            # No silent first-N subset and no financial archive/consumed-window deletion.
            return {
                "rows": rows,
                "records": [],
                "manifest": {
                    "rows": len(rows),
                    "source_decisions": count,
                    "source_bytes": total,
                    "execution_status": "Dependencies exceed eight-MiB budget; labels unavailable",
                    "older_rows_omitted": False,
                },
                "source_files": source_hashes(),
            }
        records = db.execute(
            "SELECT id,at,sha256,payload FROM evidence_records WHERE kind='decision' AND at<=? "
            "ORDER BY id",
            (as_of,),
        ).fetchall()
        frozen = [
            {
                "id": r["id"],
                "at": r["at"],
                "sha256": r["sha256"],
                "payload": json.loads(r["payload"]),
            }
            for r in records
        ]
        return {
            "rows": rows,
            "records": frozen,
            "manifest": {
                "rows": len(rows),
                "source_decisions": len(records),
                "source_bytes": total,
                "execution_status": "Dependencies frozen; target reconciliation pending",
                "older_rows_omitted": False,
            },
            "source_files": source_hashes(),
        }


def mature_snapshot(snapshot: dict[str, Any], as_of: float) -> list[dict[str, Any]]:
    if snapshot.get("source_files") != source_hashes():
        raise ValueError("Frozen execution source changed")
    rows: list[dict[str, Any]] = snapshot["rows"]
    records = snapshot["records"]
    verified: dict[str, dict[str, Any]] = {}
    # Every retained episode, under the existing 512-episode / eight-MiB / 25-second limits.
    for row in rows:
        if records:
            row["executable_label"] = executable_label(row["descriptor"], records, as_of, verified)
        elif row["executable_label"] is None:
            row["executable_label"] = {
                "status": "unavailable",
                "reason": "Declared execution dependencies unavailable",
            }
    return rows
