"""One operator-requested complete capture window; no trading or model authority."""

import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading.paper_engine import PaperEngine


class WindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: Literal["recorded-execution-window-v1"] = "recorded-execution-window-v1"
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{12,64}$")
    not_before: float = Field(ge=0)
    horizon_seconds: Literal[2700] = 2700
    start_grace_seconds: int = Field(default=600, ge=1, le=600)
    max_records: int = Field(default=10000, ge=541, le=10000)
    max_bytes: int = Field(default=16_000_000_000, ge=1024**2, le=16_000_000_000)


class ExecutionWindow:
    """Capture every committed tick within a finite request, without waiving guards.

    A restart or omission invalidates the request. A captured horizon is a
    candidate for offline reconciliation, never a completed execution proof.
    """

    def __init__(self, directory: Path):
        self.request: WindowRequest | None = None
        self._persisted: str | None = None
        self.path = directory / "execution-window-status.json"
        self.status: dict[str, Any] = {"state": "disabled", "financial_authority": False}
        request_path = directory / "execution-window-request.json"
        if not request_path.exists():
            return
        try:
            if request_path.is_symlink() or request_path.stat().st_size > 4096:
                raise ValueError("Use a bounded ordinary window request file")
            self.request = WindowRequest.model_validate(json.loads(request_path.read_text()))
            self.status.update(state="armed", request=self.request.model_dump(), records=0, bytes=0)
            if self.path.exists():
                if self.path.is_symlink() or self.path.stat().st_size > 16384:
                    raise ValueError("Use a bounded ordinary window status file")
                previous = json.loads(self.path.read_text())
                if not isinstance(previous, dict):
                    raise ValueError("Invalid finite-window status shape")
                if previous.get("request", {}).get("request_id") == self.request.request_id:
                    if previous.get("state") not in {
                        "armed",
                        "capturing",
                        "incomplete",
                        "captured_pending_reconciliation",
                    }:
                        raise ValueError("Invalid finite-window status state")
                    self.status = previous
                    if self.status["state"] in {"armed", "capturing"}:
                        self.fail(
                            "Restart interrupted this request; missing inputs cannot be bridged"
                        )
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.request = None
            self.status = {
                "state": "refused",
                "reason": "Invalid capture request or status",
                "financial_authority": False,
            }

    def fail(self, reason: str) -> None:
        if self.status["state"] in {"armed", "capturing", "captured_pending_reconciliation"}:
            self.status.update(state="incomplete", reason=reason)

    def selected(self, at: float) -> bool:
        request = self.request
        if request is None or self.status["state"] not in {"armed", "capturing"}:
            return False
        if self.status["state"] == "armed":
            if at > request.not_before + request.start_grace_seconds:
                self.fail("No supported starting observation within the finite start grace")
                return False
            return at >= request.not_before
        return True  # Includes the first actual tick at or beyond the complete horizon.

    def attach(self, packet: dict[str, Any], omissions: int) -> None:
        if not self.selected(packet["at"]):
            return
        assert self.request is not None
        frame = packet["frames"].get("BTCUSD")
        rows = packet["bars"].get("BTCUSD", [])
        origin = packet["feature_origin"].get("BTCUSD")
        at = packet["at"]
        supported = (
            frame is not None
            and 0 <= at - frame["observed"] <= 5
            and len(rows) >= 305
            and all(
                b["open_ms"] == a["open_ms"] + 60000 for a, b in zip(rows, rows[1:], strict=False)
            )
            and all(r["close_ms"] < at * 1000 and r["available_at"] <= at for r in rows)
            and origin is not None
            and origin["available_at"] <= at
            and not origin["candle_error"]
            and 0 <= at * 1000 - rows[-1]["close_ms"] <= 90000
        )
        if not supported:
            if self.status["state"] == "capturing":
                self.fail(
                    "Required BTCUSD book, causal minute warmup or continuous input is absent"
                )
            return
        if self.status["state"] == "armed":
            self.status.update(
                state="capturing",
                first_at=at,
                required_end_at=at + 2700,
                omissions_at_start=omissions,
            )
        # The shared counter includes auxiliary wire/summary refusals. Required
        # tick queue/commit/archive failures independently invalidate the request.
        # Each complete tick already retains its original supported book/candles.
        self.status["auxiliary_capture_omissions_since_start"] = (
            omissions - self.status["omissions_at_start"]
        )
        packet["execution_window"] = {
            "request_id": self.request.request_id,
            "first_at": self.status["first_at"],
            "required_end_at": self.status["required_end_at"],
            "wire_coverage": (
                "Original financial inputs per tick; auxiliary wire capture remains sampled"
            ),
        }

    def committed(self, packet: dict[str, Any]) -> bool:
        if not packet.get("execution_window") or self.status["state"] != "capturing":
            return False
        assert self.request is not None
        commit = packet.get("financial_commit") or {}
        revision = commit.get("revision")
        prior = self.status.get("last_revision")
        if not isinstance(revision, int) or (prior is not None and revision != prior + 1):
            self.fail("Intervening financial control commit was not captured; retain the boundary")
            return False
        if self.status.get("last_at") is not None and packet["at"] - self.status["last_at"] > 5:
            self.fail("Financial observation gap exceeds five seconds")
            return False
        size = len(json.dumps(packet, allow_nan=False).encode())
        if (
            self.status["records"] + 1 > self.request.max_records
            or self.status["bytes"] + size > self.request.max_bytes
        ):
            self.fail("The finite capture record/byte budget was reached")
            return False
        self.status.update(
            records=self.status["records"] + 1,
            bytes=self.status["bytes"] + size,
            last_at=packet["at"],
            last_revision=revision,
        )
        if packet["at"] >= self.status["required_end_at"]:
            self.status.update(state="captured_pending_reconciliation")
        return True

    def persist(self) -> None:
        if self.request is None:
            return
        identity = json.dumps(self.status, sort_keys=True, allow_nan=False)
        if identity == self._persisted:
            return
        value = {**self.status, "receipt_at": time.time(), "offline_reconciliation_required": True}
        partial = self.path.with_suffix(".partial")
        partial.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
        partial.replace(self.path)
        self._persisted = identity


def tick_preamble(engine: PaperEngine, command: dict[str, Any]) -> None:
    """The original runtime operations, replayed from recorded typed inputs only."""
    if set(command) != {
        "feed_model",
        "status_changed",
        "errors",
        "sources",
        "notices",
        "universe_plan",
        "bars_added",
        "book_sequences",
    }:
        raise ValueError("Unsupported pre-tick command")
    if not isinstance(command["feed_model"], str) or type(command["status_changed"]) is not bool:
        raise ValueError("Invalid pre-tick feed status")
    if type(command["bars_added"]) is not int or command["bars_added"] < 0:
        raise ValueError("Invalid recorded candle count")
    if engine.state["model"] != command["feed_model"]:
        previous = engine.state["model"]
        for name, account in engine.state["accounts"].items():
            for symbol, order in list(account["pending"].items()):
                order.setdefault("model", previous)
                if order["side"] == "buy":
                    engine.cancel(name, account, symbol, "Feed model upgraded; re-evaluate")
        engine.state["model"] = command["feed_model"]
        engine.emit(
            "feed_model_changed",
            "primary",
            {
                "previous": previous,
                "selected": command["feed_model"],
                "note": "Risk, fees and one-second fill delay unchanged",
            },
        )
    if command["status_changed"]:
        engine.emit(
            "feed_status", "system", {"errors": command["errors"], "sources": command["sources"]}
        )
    for notice in command["notices"]:
        if notice["kind"] == "futures_context":
            engine.record_futures_context(notice["body"])
        else:
            engine.emit(notice["kind"], "system", notice["body"])
    engine.universe_experiment(command["universe_plan"])
    engine.state["study_bars"] += command["bars_added"]
    engine.state["book_sequences"] = command["book_sequences"]


def preamble_hash() -> str:
    import hashlib

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def replay_preamble(engine: PaperEngine, packet: dict[str, Any]) -> None:
    if "pre_tick" in packet:
        if packet["source_files"].get("execution_window.py") != preamble_hash():
            raise ValueError("Recorded pre-tick source changed")
        tick_preamble(engine, packet["pre_tick"])


def replay_tick(engine: PaperEngine, packet: dict[str, Any], frames: dict[str, Any]) -> None:
    from copy import deepcopy

    replay_preamble(engine, packet)
    engine.tick(frames, deepcopy(packet["study"]))
