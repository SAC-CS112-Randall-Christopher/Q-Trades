import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from trading.api import create_app
from trading.config import Settings


def health_module():
    path = Path(__file__).resolve().parents[1] / "scripts/qtrades_health.py"
    spec = importlib.util.spec_from_file_location("simple_health", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "field", ["paper", "paper_fresh", "journal_balanced", "paper_error_reported", "code_commit"]
)
def test_missing_or_wrong_health_does_not_claim_updated(field):
    commit = "a" * 40
    value = dict(
        service="running",
        mode="paper",
        paper="running",
        paper_fresh=True,
        journal_balanced=True,
        paper_error_reported=False,
        code_commit=commit,
    )
    helper = health_module()
    assert helper.healthy(value, commit)
    value.pop(field)
    assert not helper.healthy(value, commit)
    value[field] = "unexpected"
    assert not helper.healthy(value, commit)


def test_small_health_freezes_commit_at_start_and_uses_account_receipts(tmp_path):
    commit = "a" * 40
    (tmp_path / "installed-commit.txt").write_text(commit)
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app) as client:
        app.state.paper = SimpleNamespace(
            running=True, state={"last_tick": time.time()}, receipts={"balanced": True}, error=None
        )
        response = client.get("/api/health").json()
        assert health_module().healthy(response, commit)
        (tmp_path / "installed-commit.txt").write_text("b" * 40)
        assert client.get("/api/health").json()["code_commit"] == commit
        app.state.paper.receipts["balanced"] = False
        assert not health_module().healthy(client.get("/api/health").json(), commit)
        for route in ("/api/installation", "/api/installation/check", "/api/installation/activate"):
            assert client.get(route).status_code == 404


def test_invalid_installed_marker_is_not_exposed(tmp_path):
    (tmp_path / "installed-commit.txt").write_text("private-not-a-commit")
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    ) as client:
        response = client.get("/api/health")
        assert response.json()["code_commit"] is None
        assert "private-not-a-commit" not in response.text
