"""Real disposable Git plus a fake native adapter: no Windows task/account mutations."""

import copy
from pathlib import Path

import pytest
from test_local_updates import fake_build, git, repository  # noqa: F401

from trading import local_activation as a
from trading import local_updates as u
from trading.activation_state import ACK_NAME, digest, runtime_binding


class Native:
    def __init__(self, root, runtime):
        self.root, self.runtime = str(root), runtime
        self.calls = []
        self.fail = None
        self.fail_after = False
        self.running = True
        self.commit = None

    def call(self, action, plan):
        self.calls.append(action)
        if action == self.fail and not self.fail_after:
            raise u.UpdateError("injected native failure")
        if action == "inspect":
            return {
                "code_root": self.root,
                "owned": self.running,
                "enabled": True,
                "signature": "unchanged",
                "action": {"WorkingDirectory": self.root},
            }
        if action == "prepare_desktop":
            return {"before_hash": "old", "new_hash": "new"}
        if action == "stop":
            self.running = False
        if action == "configure_target":
            self.root = plan["target_root"]
        if action == "configure_previous":
            self.root = plan["old_root"]
        if action == "start":
            self.running = True
            self.commit = plan["launch"]["commit"]
            u.write_record(
                self.runtime / "data" / ACK_NAME,
                {
                    "operation": plan["id"],
                    "commit": self.commit,
                    "checkpoint": digest(plan["baseline"]),
                },
            )
        if action == self.fail:
            raise u.UpdateError("injected failure after side effect")
        return {"ok": True}

    def status(self):
        return {
            "paper": {
                "enabled": True,
                "running": self.running,
                "stale": False,
                "error": None,
                "journal": {"balanced": True},
            }
        }

    def installation(self):
        return {"running_commit": self.commit, "running_source_dirty": False}


@pytest.fixture
def setup(repository, monkeypatch):  # noqa: F811 - imported pytest fixture
    updater, bare, main, releases = repository
    for name in (
        *a.FINANCIAL_FILES,
        "pyproject.toml",
        "src/trading/activation_state.py",
        "scripts/QTradesNativeUpdate.ps1",
    ):
        p = main / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# isolated fixture, never executed\n")
    git(main, "add", ".")
    git(main, "commit", "-m", "Disposable compatible financial source")
    git(main, "push", str(bare), "main")
    git(updater.source, "fetch", "origin")
    git(updater.source, "merge", "--ff-only", "origin/main")
    result = updater.prepare(releases, fake_build)
    runtime = updater.status_dir.parent
    for name in ["configs/paper.toml", "compose.yaml"]:
        p = runtime / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("test only")
    snapshot = {
        "runtime_binding": runtime_binding(runtime),
        "paper": {
            "state_sha256": "baseline",
            "journal_sha256": "retained",
            "revision": 1,
        },
        "options": None,
    }
    monkeypatch.setattr(a, "capture_accounts", lambda *args, **kwargs: copy.deepcopy(snapshot))
    native = Native(updater.source, runtime)
    manager = a.LocalActivation(updater.source, runtime, native)
    return manager, native, Path(result["release_directory"]), result["commit"], snapshot


def test_preflight_has_no_native_mutations(setup):
    manager, native, release, commit, _ = setup
    result = manager.activate(release, commit)
    assert result["phase"] == "preflight_passed"
    assert native.calls == ["inspect"]
    assert not manager.path.exists()


def test_activation_selects_main_preserves_data_and_records_startup_proof(setup):
    manager, native, release, commit, snapshot = setup
    before = (manager.runtime / "data/journal.sqlite3").read_bytes()
    result = manager.activate(release, commit, apply=True)
    assert result["phase"] == "verified"
    assert native.root == str(release)
    assert (
        native.calls.index("stop")
        < native.calls.index("configure_target")
        < native.calls.index("start")
    )
    assert native.calls[-1] == "install_desktop"
    record = u.read_record(manager.path)
    assert record["baseline"] == snapshot
    assert (manager.runtime / "data/journal.sqlite3").read_bytes() == before
    assert len(list((manager.runtime / "data/update-receipts").glob("*.json"))) == 5


@pytest.mark.parametrize("step", ["stop", "configure_target", "start", "install_desktop"])
@pytest.mark.parametrize("after", [False, True])
def test_failure_before_or_after_native_side_effect_has_recoverable_receipt(setup, step, after):
    manager, native, release, commit, _ = setup
    native.fail, native.fail_after = step, after
    with pytest.raises(u.UpdateError, match="recover --apply"):
        manager.activate(release, commit, apply=True)
    assert u.read_record(manager.path)["phase"] == "recovery_required"
    with pytest.raises(u.UpdateError, match="unfinished"):
        manager.activate(release, commit, apply=True)
    native.fail = None
    calls = len(native.calls)
    assert manager.recover()["native_changes"] is False
    assert len(native.calls) == calls
    result = manager.recover(apply=True)
    assert result["phase"] == "recovered" and result["data_restored"] is False
    assert native.root == str(manager.source) and native.running
    calls = len(native.calls)
    assert manager.recover(apply=True)["already_completed"]
    assert len(native.calls) == calls


def test_recovery_does_not_overwrite_account_work_done_after_new_start(setup):
    manager, native, release, commit, snapshot = setup
    native.fail = "install_desktop"
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    # A new account transaction happened before verification failed: never restore the old DB.
    snapshot["paper"].update(revision=2, state_sha256="later-trade", journal_sha256="new-history")
    native.fail = None
    manager.recover(apply=True)
    assert u.read_record(manager.path)["baseline"]["paper"]["revision"] == 2


def test_changed_previous_source_refuses_recovery_before_any_stop(setup):
    manager, native, release, commit, _ = setup
    native.fail = "start"
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    (manager.source / "src/trading/paper_engine.py").write_text("new local work")
    native.fail = None
    before = native.calls[:]
    with pytest.raises(u.UpdateError, match="Previous code changed"):
        manager.recover(apply=True)
    assert native.calls == before


def test_incompatible_financial_code_does_not_silently_downgrade(setup):
    manager, native, release, commit, _ = setup
    native.fail = "start"
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    (release / "src/trading/paper_engine.py").write_text("different policy")
    before = native.calls[:]
    with pytest.raises(u.UpdateError, match="compatibility review"):
        manager.recover(apply=True)
    assert native.calls == before


def test_wrong_unmerged_or_modified_release_is_rejected_before_stop(setup):
    manager, native, release, commit, _ = setup
    (release / "src/trading/__main__.py").write_text("local change")
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    assert not native.calls


def test_unknown_health_is_not_permission_to_restart(setup):
    manager, native, release, commit, _ = setup
    native.status = lambda: {"paper": {"running": "true"}}
    with pytest.raises(u.UpdateError, match="healthy"):
        manager.activate(release, commit, apply=True)
    assert native.calls == ["inspect"]


def test_foreign_process_not_restarted(setup):
    manager, native, release, commit, _ = setup
    native.running = False
    with pytest.raises(u.UpdateError, match="ownership"):
        manager.activate(release, commit, apply=True)
    assert native.calls == ["inspect"]


def test_account_and_configuration_drift_after_stop_blocks_start(setup):
    manager, native, release, commit, snapshot = setup
    call = native.call

    def drift(action, plan):
        result = call(action, plan)
        if action == "stop":
            snapshot["runtime_binding"] = "changed_config"
        return result

    native.call = drift
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    assert "start" not in native.calls


def test_operation_lock_blocks_concurrent_activation(setup):
    manager, native, release, commit, _ = setup
    lock = a.CollectorLock(manager.runtime / "data/main-update.lock")
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            manager.activate(release, commit, apply=True)
    finally:
        lock.release()
    assert not native.calls


def test_installer_metadata_is_not_an_http_activation_route(tmp_path):
    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings

    with TestClient(create_app(Settings(), tmp_path / "monitor", background=False)) as client:
        assert client.post("/api/installation/activate").status_code == 404
        assert client.post("/api/installation/recover").status_code == 404


def test_historical_replay_health_does_not_require_a_nonexistent_live_stale_flag():
    status = {
        "paper": {
            "enabled": True,
            "running": True,
            "stale": False,
            "error": None,
            "journal": {"balanced": True},
        },
        "options": {
            "enabled": True,
            "running": True,
            "error": "Free historical data budget exhausted",
            "journal": {"balanced": True},
        },
    }
    assert a.healthy(status, options_required=True)
    status["options"]["running"] = False
    assert not a.healthy(status, options_required=True)
    status["options"]["running"] = True
    status["options"]["journal"]["balanced"] = False
    assert not a.healthy(status, options_required=True)


def test_saved_recovery_path_traversal_identifier_is_rejected(setup):
    manager, native, release, commit, _ = setup
    native.fail = "start"
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    record = u.read_record(manager.path)
    record["id"] = "../../outside"
    u.write_record(manager.path, record)
    before = native.calls[:]
    with pytest.raises(u.UpdateError, match="identifier"):
        manager.recover(apply=True)
    assert native.calls == before


def test_prepared_commit_must_have_been_on_authoritative_main(setup):
    manager, native, release, _, _ = setup
    git(release, "config", "user.email", "test@example.invalid")
    git(release, "config", "user.name", "test")
    (release / "unmerged.txt").write_text("unapproved branch")
    git(release, "add", "unmerged.txt")
    git(release, "commit", "-m", "Never merged")
    commit = git(release, "rev-parse", "HEAD")
    receipt = u.read_record(release / u.RECEIPT_NAME)
    receipt.update(commit=commit, tree=git(release, "rev-parse", "HEAD^{tree}"))
    u.write_record(release / u.RECEIPT_NAME, receipt)
    with pytest.raises(u.UpdateError):
        manager.activate(release, commit, apply=True)
    assert not native.calls


def test_preflight_preserves_preparation_and_repeat_activation_does_not_restart(setup):
    manager, native, release, commit, _ = setup
    manager.activate(release, commit)
    receipt = u.read_record(manager.runtime / "data" / u.STATUS_NAME)
    assert receipt["phase"] == "prepared"
    assert receipt["prepared_directory"] == str(release)
    manager.activate(release, commit, apply=True)
    stopped = native.calls.count("stop")
    assert manager.activate(release, commit, apply=True)["phase"] == "already_running"
    assert native.calls.count("stop") == stopped


def test_archive_failure_cannot_publish_a_successful_activation(setup, monkeypatch):
    manager, _, release, commit, _ = setup
    plan = manager.inspect_plan(release, commit)
    manager.save(plan, "starting")
    before = u.read_record(manager.path)
    original = a.write_record

    def no_archive(path, value):
        if path.parent.name == "update-receipts":
            raise OSError("synthetic archive capacity failure")
        return original(path, value)

    monkeypatch.setattr(a, "write_record", no_archive)
    with pytest.raises(OSError):
        manager.save(plan, "verified")
    assert u.read_record(manager.path) == before


def test_new_financial_policy_cannot_begin_a_native_cutover(setup, monkeypatch):
    manager, native, release, commit, _ = setup
    original = a.financial_fingerprint
    monkeypatch.setattr(
        a,
        "financial_fingerprint",
        lambda path: "different-financial-policy" if path == release else original(path),
    )
    with pytest.raises(u.UpdateError, match="compatibility review"):
        manager.activate(release, commit, apply=True)
    assert native.calls == ["inspect"]
    assert not manager.path.exists()


def test_financial_compatibility_ignores_only_windows_newline_translation(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for name in a.FINANCIAL_FILES:
        for root, value in (
            (old, b"# same source\nvalue = 1\n"),
            (new, b"# same source\r\nvalue = 1\r\n"),
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
    assert a.financial_fingerprint(old) == a.financial_fingerprint(new)
    (new / a.FINANCIAL_FILES[0]).write_bytes(b"# same source\r\nvalue = 2\r\n")
    assert a.financial_fingerprint(old) != a.financial_fingerprint(new)
