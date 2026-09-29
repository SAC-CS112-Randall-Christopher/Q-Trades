import hashlib

from fastapi.testclient import TestClient

from trading.api import create_app
from trading.config import Settings


def test_no_order_mode_or_ai_routes_and_pause_survives_restart(tmp_path):
    path = tmp_path / "db"
    with TestClient(create_app(Settings(), path, background=False)) as client:
        initial = client.get("/api/status")
        assert initial.status_code == 200
        assert initial.json()["ai"]["enabled"] is False
        for route in ("/api/orders", "/api/live", "/api/ai", "/api/funding"):
            assert client.post(route).status_code == 404
        assert client.post("/api/collector", json={"action": "pause"}).status_code == 403
        assert (
            client.post(
                "/api/collector",
                json={"action": "pause"},
                headers={"X-Local-Operator": "1", "Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        response = client.post(
            "/api/collector",
            json={"action": "pause"},
            headers={"X-Local-Operator": "1", "Origin": "http://testserver"},
        )
        assert response.json() == {"paused": True}
        assert client.get("/api/status").json()["runtime_state"] == "paused"
        capture = client.get("/api/capture")
        assert capture.headers["X-Content-SHA256"] == hashlib.sha256(capture.content).hexdigest()
        assert capture.headers["Cache-Control"] == "no-store"
        assert client.get("/api/status", headers={"Host": "untrusted.example"}).status_code == 400
    with TestClient(create_app(Settings(), path, background=False)) as reopened:
        assert reopened.get("/api/status").json()["paused"] is True
