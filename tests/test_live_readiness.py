from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trading.api import create_app
from trading.config import Settings
from trading.live_readiness import packet


def test_packet_distinguishes_total_capital_fees_finality_and_paper_role():
    state = {
        "evidence_kind": "synthetic_qa",
        "learning": {"incumbent": "forward-example", "role_version": 2, "reports": {"r": {}}},
    }
    value = packet(state)
    assert value["decision"] == "not_ready" and value["live_execution"] is False
    assert value["risk_envelope"]["live_candidate"] is None
    assert value["risk_envelope"]["live_capital_allocated_usd"] == "0"
    assert value["current_paper_evidence"]["paper_role_version"] == 2
    assert "reversed" in " ".join(value["facts"])
    assert Decimal(value["economics"][0]["published_fee_only_round_trip_usd"]) == Decimal(
        50
    ) * 2 * Decimal("0.0002") / Decimal("1.0002")
    assert value["public_symbols"][0]["quantity_step"] == "0.00001"
    assert all(s["url"].startswith("https://") for s in value["sources"])
    old_hash = value["facts_sha256"]
    value["blockers"].clear()
    assert packet()["facts_sha256"] == old_hash and packet()["blockers"]


def test_readiness_is_read_only_and_cannot_grant_live_permission(tmp_path):
    with TestClient(create_app(Settings(), tmp_path / "db", background=False)) as client:
        first = client.get("/api/readiness")
        assert first.status_code == 200 and first.headers["Cache-Control"] == "no-store"
        assert client.post("/api/readiness", json={"approve": True}).status_code == 405
        assert client.post("/api/live").status_code == 404
        assert client.get("/api/readiness").json()["facts_sha256"] == first.json()["facts_sha256"]
    with pytest.raises(ValidationError):
        Settings(live_enabled=True)
