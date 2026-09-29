"""Real disposable Git remotes; no GitHub writes, account data or trading processes."""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trading import local_updates as u
from trading.api import create_app
from trading.config import Settings
from trading.ownership import CollectorLock


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty-git-config"))
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "test@example.invalid")
    git(main, "config", "user.name", "Disposable test")
    for relative in u.REQUIRED:
        path = main / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if relative.endswith(".json") else "# test\n")
    (main / "configs").mkdir()
    (main / "configs/local-release.json").write_text(
        json.dumps(
            {
                "contract": u.RELEASE_CONTRACT,
                "mode": "paper",
                "automatic_activation": False,
            }
        )
    )
    (main / ".gitignore").write_text("apps/web/dist/\n.qtrades-release.json\n")
    git(main, "add", ".")
    git(main, "commit", "-m", "Disposable main")
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(main), str(bare)], check=True, capture_output=True
    )
    source = tmp_path / "checkout"
    subprocess.run(["git", "clone", str(bare), str(source)], check=True, capture_output=True)
    monkeypatch.setattr(
        u, "REPOSITORY", str(bare)
    )  # Test injection only; CLI has no origin override.
    status = tmp_path / "runtime" / "data"
    status.mkdir(parents=True)
    (status / "journal.sqlite3").write_bytes(b"retained-history")
    (status / "paper-database.json").write_text('{"test_marker":"not read by updater"}')
    monkeypatch.setattr(
        u.shutil, "disk_usage", lambda _: type("Disk", (), {"free": 10 * 1024**3})()
    )
    return u.MainUpdates(source, status), bare, main, tmp_path / "releases"


def fake_build(root):
    (root / "apps/web/dist/assets").mkdir(parents=True)
    (root / "apps/web/dist/index.html").write_text("test build, not the actual application")
    (root / "apps/web/dist/assets/app.js").write_text("// test asset")


def retained(updater):
    return {
        p.name: p.read_bytes()
        for p in updater.status_dir.iterdir()
        if p.name in {"journal.sqlite3", "paper-database.json"}
    }


def test_check_fetches_main_without_switching_branch_or_touching_accounts(repository):
    updater, _, _, _ = repository
    git(updater.source, "switch", "-c", "work-in-progress")
    before = retained(updater)
    head = git(updater.source, "rev-parse", "HEAD")
    result = updater.check()
    assert result["phase"] == "available" and result["main_commit"] == head
    assert git(updater.source, "branch", "--show-current") == "work-in-progress"
    assert retained(updater) == before


def test_prepare_uses_exact_main_not_development_branch_and_keeps_prior_release(repository):
    updater, _, _, releases = repository
    main = git(updater.source, "rev-parse", "HEAD")
    git(updater.source, "config", "user.email", "test@example.invalid")
    git(updater.source, "config", "user.name", "test")
    git(updater.source, "switch", "-c", "candidate")
    (updater.source / "candidate.txt").write_text("never deploy this branch")
    git(updater.source, "add", ".")
    git(updater.source, "commit", "-m", "unmerged experiment")
    before = retained(updater)
    result = updater.prepare(releases, fake_build)
    release = Path(result["release_directory"])
    assert result["commit"] == main
    assert not (release / "candidate.txt").exists()
    assert not (release / "data").exists()
    assert result["state"] == "prepared" and result["activation"] == "not_activated"
    assert len(result["assets"]) == 2
    assert retained(updater) == before
    second = updater.prepare(releases, fake_build)
    assert second["release_directory"] != str(release)
    assert release.exists()


def test_dirty_checkout_rejected_without_discarding_changes(repository):
    updater, _, _, releases = repository
    path = updater.source / "uncommitted.txt"
    path.write_text("keep me")
    with pytest.raises(u.UpdateError, match="local changes"):
        updater.prepare(releases, fake_build)
    assert path.read_text() == "keep me" and not releases.exists()


def test_failed_prepare_keeps_old_release_and_account_history(repository):
    updater, _, _, releases = repository
    good = updater.prepare(releases, fake_build)
    before = retained(updater)

    def broken(_):
        raise u.UpdateError("synthetic dependency outage")

    with pytest.raises(u.UpdateError, match="outage"):
        updater.prepare(releases, broken)
    assert Path(good["release_directory"]).is_dir()
    assert len(list(releases.iterdir())) == 2
    assert u.read_record(updater.status_path)["phase"] == "failed"
    assert retained(updater) == before


def test_offline_check_preserves_last_main_and_installed_data(repository, monkeypatch):
    updater, _, _, _ = repository
    previous = updater.check()
    before = retained(updater)
    monkeypatch.setattr(updater, "_check", lambda: (_ for _ in ()).throw(u.UpdateError("offline")))
    with pytest.raises(u.UpdateError):
        updater.check()
    failed = u.read_record(updater.status_path)
    assert failed["main_commit"] == previous["main_commit"]
    assert failed["checked_at"] == previous["checked_at"] and failed["phase"] == "failed"
    assert retained(updater) == before


def test_concurrent_operations_are_rejected_without_overwriting_active_status(repository):
    updater, _, _, releases = repository
    lock = CollectorLock(updater.status_dir / "main-update.lock")
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            updater.check()
        with pytest.raises(RuntimeError):
            updater.prepare(releases, fake_build)
        assert not updater.status_path.exists()
    finally:
        lock.release()
    assert updater.check()["phase"] == "available"


def test_unexpected_origin_rejected(repository):
    updater, _, _, _ = repository
    git(updater.source, "remote", "set-url", "origin", "https://example.invalid/foreign.git")
    with pytest.raises(u.UpdateError, match="expected"):
        updater.check()
    assert u.source_identity(updater.source)["commit"] is None


@pytest.mark.parametrize("nested", ["source", "data", "ancestor"])
def test_release_storage_cannot_overlap_source_or_runtime(repository, nested):
    updater, _, _, _ = repository
    destination = {
        "source": updater.source / "release",
        "data": updater.status_dir / "release",
        "ancestor": updater.status_dir.parent.parent,
    }[nested]
    with pytest.raises(u.UpdateError, match="separate"):
        updater.prepare(destination, fake_build)


def test_main_without_release_contract_is_not_installable(repository):
    updater, bare, main, releases = repository
    (main / "configs/local-release.json").unlink()
    git(main, "add", "-u")
    git(main, "commit", "-m", "no deployment contract")
    git(main, "push", str(bare), "main")
    assert updater.check()["phase"] == "no_release"
    with pytest.raises(u.UpdateError, match="merged"):
        updater.prepare(releases, fake_build)
    assert not releases.exists()


@pytest.mark.parametrize("file", ["data/settings.json", ".env", "secret.key"])
def test_tracked_runtime_files_are_rejected_before_build(repository, file):
    updater, bare, main, releases = repository
    target = main / file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("synthetic fixture, not a secret")
    git(main, "add", "-f", file)
    git(main, "commit", "-m", "bad release fixture")
    git(main, "push", str(bare), "main")
    with pytest.raises(u.UpdateError, match="tracked|prohibited"):
        updater.prepare(releases, lambda _: pytest.fail("builder must not run"))


def test_source_change_during_build_rejects_candidate(repository):
    updater, _, _, releases = repository

    def tamper(root):
        fake_build(root)
        (root / "requirements-lock.txt").write_text("changed\n")

    with pytest.raises(u.UpdateError, match="modified source"):
        updater.prepare(releases, tamper)


def test_process_version_is_captured_at_start_and_status_never_runs_git(repository, monkeypatch):
    updater, _, _, _ = repository
    started = u.source_identity(updater.source)
    assert started["commit"] and started["dirty"] is False
    (updater.source / "src/trading/__main__.py").write_text("# later edit")
    assert u.source_identity(updater.source)["dirty"] is True
    monkeypatch.setattr(u, "git", lambda *_: pytest.fail("GET must not execute Git"))
    assert u.public_status(started, updater.status_path)["running_source_dirty"] is False


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"phase":{}}',
        '{"phase":"preparing","operation_started_at":"bad"}',
        '{"phase":"preparing","operation_started_at":NaN}',
    ],
)
def test_malformed_status_does_not_stop_application(tmp_path, payload):
    path = tmp_path / "status.json"
    path.write_text(payload)
    status = u.public_status({}, path)
    assert status["phase"] in {"not_checked", "failed"}
    assert status["automatic_activation"] is False


def test_status_does_not_expose_injected_paths_or_error_text(tmp_path):
    path = tmp_path / "status.json"
    u.write_record(
        path, {"phase": "failed", "error": "DO_NOT_EXPOSE", "main_commit": "DO_NOT_EXPOSE"}
    )
    status = json.dumps(u.public_status({}, path))
    assert "DO_NOT_EXPOSE" not in status


def test_old_in_progress_receipt_is_reported_as_failed(tmp_path):
    path = tmp_path / "status.json"
    u.write_record(path, {"phase": "preparing", "operation_started_at": time.time() - 3601})
    assert u.public_status({}, path)["phase"] == "failed"


def test_no_git_does_not_prevent_startup(repository, monkeypatch):
    updater, _, _, _ = repository
    monkeypatch.setattr(u, "git", lambda *_: (_ for _ in ()).throw(u.UpdateError("missing")))
    assert u.source_identity(updater.source) == {
        "commit": None,
        "dirty": None,
        "kind": "unversioned",
    }


def test_installation_api_get_readonly_local_authority_and_no_activation(tmp_path, monkeypatch):
    calls = []
    event_loop_threads = []

    def check(self):
        calls.append(threading.get_ident())
        u.write_record(
            self.status_path,
            {"phase": "no_release", "main_commit": "a" * 40, "checked_at": time.time()},
        )

    monkeypatch.setattr(u.MainUpdates, "check", check)
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)

    @app.get("/test-loop-thread")
    async def thread():
        event_loop_threads.append(threading.get_ident())
        return {}

    with TestClient(app) as client:
        client.get("/test-loop-thread")
        assert client.get("/api/installation").headers["Cache-Control"] == "no-store"
        assert calls == []
        assert client.post("/api/installation/check").status_code == 403
        assert (
            client.post(
                "/api/installation/check",
                headers={"X-Local-Operator": "1", "Origin": "https://testserver"},
            ).status_code
            == 403
        )
        headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
        result = client.post("/api/installation/check", headers=headers)
        assert result.status_code == 200 and result.json()["phase"] == "no_release"
        assert calls[0] != event_loop_threads[0]
        assert client.post("/api/installation/check", headers=headers).status_code == 429
        assert client.post("/api/installation/activate", headers=headers).status_code == 404
        assert client.get("/api/health").status_code == 200


def test_api_check_failure_preserves_running_service(tmp_path, monkeypatch):
    def fail(_):
        raise u.UpdateError("synthetic failure")

    monkeypatch.setattr(u.MainUpdates, "check", fail)
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    ) as client:
        assert (
            client.post("/api/installation/check", headers={"X-Local-Operator": "1"}).status_code
            == 503
        )
        assert client.get("/api/health").json()["service"] == "running"


def test_no_dashboard_output_is_not_a_prepared_release(repository):
    updater, _, _, releases = repository
    with pytest.raises(u.UpdateError, match="entry page"):
        updater.prepare(releases, lambda _: None)


def test_build_cannot_add_untracked_application_code(repository):
    updater, _, _, releases = repository

    def extra(root):
        fake_build(root)
        (root / "src/trading/unreviewed.py").write_text("# not approved main code\n")

    with pytest.raises(u.UpdateError, match="modified source"):
        updater.prepare(releases, extra)


def test_runtime_root_selects_existing_data_and_leaves_code_separate(tmp_path, monkeypatch):
    from trading import __main__ as cli

    runtime = tmp_path / "existing-app"
    (runtime / "data").mkdir(parents=True)
    (runtime / "data/monitor.sqlite3").write_bytes(b"retained monitor")
    (runtime / "data/paper-database.json").write_text("not consumed by this fixture")
    invoked = {}

    class Existing:
        def __init__(self, dsn):
            invoked["dsn"] = dsn

        def read(self):
            invoked["read"] = True
            return {}

        def reconcile(self):
            return {"balanced": True}

        def close(self):
            invoked["closed"] = True

    monkeypatch.setattr(cli, "PaperStore", Existing)
    monkeypatch.setattr(cli, "load_dsn", lambda path: str(path))
    monkeypatch.setattr(cli, "load_settings", lambda path: path)

    def app(*args, **kwargs):
        invoked["args"] = args
        invoked["kwargs"] = kwargs
        return "app"

    monkeypatch.setattr(cli, "create_app", app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli.sys if hasattr(cli, "sys") else __import__("sys"),
        "argv",
        ["trading", "serve", "--experiment", "--runtime-root", str(runtime)],
    )
    cli.main()
    assert invoked["args"][0] == runtime / "configs/paper.toml"
    assert invoked["args"][1] == runtime / "data/monitor.sqlite3"
    assert invoked["kwargs"]["research_evidence"] == runtime / "docs/evidence"
    assert invoked["read"] and invoked["closed"]
    assert (runtime / "data/monitor.sqlite3").read_bytes() == b"retained monitor"


def test_runtime_root_missing_history_refuses_new_application(tmp_path, monkeypatch):
    import sys

    from trading import __main__ as cli

    monkeypatch.setattr(
        sys, "argv", ["trading", "serve", "--experiment", "--runtime-root", str(tmp_path)]
    )
    monkeypatch.setattr(cli, "create_app", lambda *_args, **_kwargs: pytest.fail("must not start"))
    with pytest.raises(SystemExit):
        cli.main()
    assert not (tmp_path / "data").exists()


def test_modified_prepared_dashboard_cannot_report_a_clean_release(repository):
    updater, _, _, releases = repository
    result = updater.prepare(releases, fake_build)
    root = Path(result["release_directory"])
    assert u.source_identity(root)["kind"] == "prepared_release"
    (root / "apps/web/dist/assets/app.js").write_text("// later unrecorded build")
    identity = u.source_identity(root)
    assert identity["dirty"] is True and identity["kind"] == "modified_release"


def test_receipt_cannot_read_arbitrary_file_paths(tmp_path):
    secret = tmp_path / "credential.txt"
    secret.write_text("not a real credential")
    assert u.artifacts_match(tmp_path, {"assets": {"../credential.txt": "a" * 64}}) is False


def test_main_recheck_retains_same_prepared_release_for_explicit_activation(repository):
    updater, _, _, releases = repository
    prepared = updater.prepare(releases, fake_build)
    result = updater.check()
    assert result["phase"] == "prepared"
    assert result["prepared_directory"] == prepared["release_directory"]
    assert result["prepared_commit"] == prepared["commit"]
