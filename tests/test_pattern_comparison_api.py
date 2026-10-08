"""Normal preparation API against disposable native scanner and Lab owners."""

import copy
from types import SimpleNamespace

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from test_pattern_comparisons import build_fixture, command

from trading.api import create_app
from trading.config import Settings
from trading.pattern_comparisons import PatternComparisons

BASE = "/api/research/pattern-scanner"
OPERATOR = {"x-local-operator": "1"}


@pytest.fixture
def client_fixture(tmp_path, monkeypatch):
    f, bridge, selection = build_fixture(tmp_path / "source", monkeypatch)
    app = create_app(Settings(), tmp_path / "api" / "monitor.sqlite3", background=False)
    try:
        with TestClient(app) as client:
            app.state.pattern_scanner = f.scanner
            app.state.lab = SimpleNamespace(autonomous=bridge.controller)
            yield client, f, bridge, selection
    finally:
        f.close()


def test_operator_preparation_reopens_original_after_current_source_loss(client_fixture):
    client, f, bridge, selection = client_fixture
    before = copy.deepcopy(f.paper.state)
    described = client.get(BASE + "/comparison-source", params=selection.model_dump())
    assert described.status_code == 200, described.text
    intent = command(bridge, selection).model_dump()
    assert described.json()["finding_sha256"] == intent["expected_finding_sha256"]
    prepared = client.post(BASE + "/comparisons", json=intent, headers=OPERATOR)
    assert prepared.status_code == 200, prepared.text
    receipt = prepared.json()
    assert receipt["status"] == "supported"
    assert receipt["submitted"] is False and receipt["financial_authority"] is False
    assert receipt["evaluation"]["matched_inputs"]["archive_verified"] is True
    f.scanner.plan = None
    f.paper.history.clear()
    client.app.state.lab.autonomous = None
    reopened = client.get(BASE + "/comparisons/" + intent["request_id"])
    assert reopened.status_code == 200 and reopened.json() == receipt
    assert f.paper.state == before
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0


@pytest.mark.parametrize("headers", [{}, {**OPERATOR, "origin": "http://other.invalid"}])
def test_untrusted_preparation_has_no_retained_effect(client_fixture, headers):
    client, f, bridge, selection = client_fixture
    intent = command(bridge, selection).model_dump()
    response = client.post(BASE + "/comparisons", json=intent, headers=headers)
    assert response.status_code == 403
    assert bridge.get(intent["request_id"]) is None
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 0
    assert f.paper.state == f.original


def test_changed_intent_cannot_replace_original_preparation(client_fixture):
    client, f, bridge, selection = client_fixture
    intent = command(bridge, selection).model_dump()
    original = client.post(BASE + "/comparisons", json=intent, headers=OPERATOR)
    assert original.status_code == 200
    changed = {**intent, "event_seq": intent["event_seq"] + 1}
    response = client.post(BASE + "/comparisons", json=changed, headers=OPERATOR)
    assert response.status_code == 409
    assert client.get(BASE + "/comparisons/" + intent["request_id"]).json() == original.json()
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 1
    )


@pytest.mark.parametrize(
    "change", [{"event_seq": 2**64}, {"model_dispatch": True}, {"symbol": "BTCUSD;DROP"}]
)
def test_strict_bounds_refuse_before_preparation(client_fixture, change):
    client, f, bridge, selection = client_fixture
    intent = command(bridge, selection).model_dump()
    response = client.post(BASE + "/comparisons", json={**intent, **change}, headers=OPERATOR)
    assert response.status_code == 422
    assert bridge.get(intent["request_id"]) is None
    assert f.paper.state == f.original


@pytest.mark.parametrize(
    "failure, expected", [(KeyError("missing"), 503), (LookupError("absent"), 404)]
)
def test_missing_dependency_and_unknown_identity_remain_distinct(
    client_fixture, monkeypatch, failure, expected
):
    client, _, bridge, selection = client_fixture
    intent = command(bridge, selection).model_dump()

    def unavailable(*args):
        raise failure

    monkeypatch.setattr(PatternComparisons, "describe", unavailable)
    source = client.get(BASE + "/comparison-source", params=selection.model_dump())
    prepared = client.post(BASE + "/comparisons", json=intent, headers=OPERATOR)
    assert source.status_code == expected
    assert prepared.status_code == expected
    assert bridge.get(intent["request_id"]) is None


def test_unknown_request_remains_unknown_and_reads_create_no_work(client_fixture):
    client, f, _, _ = client_fixture
    assert client.get(BASE + "/comparisons/never-created-0001").status_code == 404
    assert client.get(BASE + "/comparisons/bad!").status_code == 422
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 0
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0


def test_normal_startup_shares_worker_and_http_preparation_owner(tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app):
        lab = app.state.lab
        owner = lab.roles.pattern_comparisons
        assert isinstance(owner, PatternComparisons)
        assert owner.scanner is app.state.pattern_scanner is lab.pattern_scanner
        assert owner.registry is lab.roles.registry is lab.registry
        assert owner.controller is lab.autonomous
        assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 0
        assert lab.autonomous is None
        assert (
            lab.registry.db.execute(
                "SELECT name FROM sqlite_master WHERE name='lab_proposals'"
            ).fetchone()
            is None
        )


def test_http_reuses_actual_worker_owner_and_refuses_foreign_identity(client_fixture, monkeypatch):
    client, f, bridge, selection = client_fixture
    client.app.state.lab.registry = f.registry
    client.app.state.lab.roles = SimpleNamespace(pattern_comparisons=bridge)
    expected = jsonable_encoder(bridge.describe(selection))

    def refuse_duplicate_owner(*args, **kwargs):
        raise AssertionError("HTTP must reuse its worker's existing preparation owner")

    monkeypatch.setattr(PatternComparisons, "__init__", refuse_duplicate_owner)
    read = client.get(BASE + "/comparison-source", params=selection.model_dump())
    assert read.status_code == 200 and read.json() == expected
    client.app.state.lab.registry = object()
    foreign = client.get(BASE + "/comparison-source", params=selection.model_dump())
    assert foreign.status_code == 503
    assert foreign.json()["detail"] == "Pattern comparison owner identity unavailable"
    assert f.paper.state == f.original
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0


def test_saved_preparations_reopen_without_browser_hint_or_current_owner(client_fixture):
    client, f, bridge, selection = client_fixture
    empty = client.get(BASE + "/comparisons")
    assert empty.status_code == 200 and empty.json()["items"] == []
    current = bridge.controller
    client.app.state.lab.autonomous = None
    first = command(bridge, selection, "pattern-comparison-0001").model_dump()
    original_wait = client.post(BASE + "/comparisons", json=first, headers=OPERATOR)
    assert original_wait.status_code == 200 and original_wait.json()["status"] == "waiting"
    client.app.state.lab.autonomous = current
    second = command(bridge, selection, "pattern-comparison-0002").model_dump()
    supported = client.post(BASE + "/comparisons", json=second, headers=OPERATOR)
    assert supported.status_code == 200 and supported.json()["status"] == "supported"
    # Recovery uses immutable preparations, even if mutable inputs disappear.
    f.scanner.plan = None
    f.paper.history.clear()
    client.app.state.lab.autonomous = None
    page = client.get(BASE + "/comparisons")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["financial_authority"] is False
    assert [item["request_id"] for item in body["items"]] == [
        second["request_id"],
        first["request_id"],
    ]
    assert "not preparation chronology" in body["order"]
    assert body["next_before"] is None
    rest = client.get(BASE + "/comparisons", params={"before": second["request_id"]})
    assert rest.status_code == 200 and len(rest.json()["items"]) == 1
    assert client.get(BASE + "/comparisons/" + first["request_id"]).json() == original_wait.json()
    assert client.get(BASE + "/comparisons/" + second["request_id"]).json() == supported.json()
    assert f.paper.state == f.original
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0


def test_missing_retained_bundle_is_unavailable_in_history_and_recovery(client_fixture):
    client, f, bridge, selection = client_fixture
    intent = command(bridge, selection).model_dump()
    prepared = client.post(BASE + "/comparisons", json=intent, headers=OPERATOR)
    assert prepared.status_code == 200
    # Corruption is confined to this disposable fixture, never operating history.
    f.registry.db.execute("DROP TRIGGER lab_bundle_retained")
    f.registry.db.execute(
        "DELETE FROM lab_bundles WHERE sha256=?", (prepared.json()["issued_bundle_sha256"],)
    )
    assert client.get(BASE + "/comparisons").status_code == 503
    assert client.get(BASE + "/comparisons/" + intent["request_id"]).status_code == 503
    assert client.post(BASE + "/comparisons", json=intent, headers=OPERATOR).status_code == 503
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 1
    )
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0
    assert f.paper.state == f.original


@pytest.mark.parametrize("cursor", ["bad!", "short", "x" * 65])
def test_history_cursor_refuses_invalid_identity_without_work(client_fixture, cursor):
    client, f, _, _ = client_fixture
    assert client.get(BASE + "/comparisons", params={"before": cursor}).status_code == 422
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 0
    assert f.paper.state == f.original
