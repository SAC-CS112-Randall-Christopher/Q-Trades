"""Isolated fixture configuration only; never reads or writes a user's Codex config."""

import json
import os
import stat
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import register_research_observer as owner

ORIGINAL = b"""# Preserve bytes, comments and every unrelated field.\r
model = "same-model"\r
unusual_number = nan\r
[mcp_servers.alpha]\r
command = "alpha"\r
args = []\r
enabled = false\r
required = true\r
[mcp_servers.alpha.env]\r
PRIVATE_TOKEN = "FIXTURE_SECRET_DO_NOT_PRINT"\r
[mcp_servers.beta]\r
url = "https://fixture.invalid/mcp"\r
enabled = true\r
required = false\r
[mcp_servers.gamma]\r
command = "gamma"\r
args = ["--same"]\r
enabled = false\r
[mcp_servers.delta]\r
command = "delta"\r
args = []\r
required = true\r
"""


@pytest.fixture
def files(tmp_path):
    interpreter, artifact, config = (
        tmp_path / name for name in ("python.exe", "observer.py", "config.toml")
    )
    interpreter.write_bytes(b"Fixture only: never execute")
    artifact.write_bytes(b"Fixture only: never execute")
    config.write_bytes(ORIGINAL)
    return interpreter, artifact, config


def backups(config):
    return list(config.parent.glob(f".{config.name}.qtrades-*.backup"))


def test_preserves_four_servers_raw_prefix_comments_secrets_and_all_values(files):
    interpreter, artifact, config = files
    before = tomllib.loads(ORIGINAL.decode())
    receipt = owner.register(*files)
    actual = config.read_bytes()
    after = tomllib.loads(actual.decode())
    assert actual.startswith(ORIGINAL)
    added = after["mcp_servers"].pop(owner.SERVER)
    assert owner.equal(after, before)
    assert added == {
        "command": str(interpreter),
        "args": ["-I", "-B", "-u", str(artifact)],
        "enabled_tools": owner.TOOLS,
        "startup_timeout_sec": 15,
        "tool_timeout_sec": 20,
    }
    assert receipt["status"] == "registered"
    assert backups(config)[0].read_bytes() == ORIGINAL
    assert not list(config.parent.glob("*.stage"))
    if os.name != "nt":
        assert stat.S_IMODE(backups(config)[0].stat().st_mode) == 0o600


def test_exact_existing_is_idempotent_without_rewrite_or_extra_backup(files, monkeypatch):
    owner.register(*files)
    config = files[2]
    before = config.read_bytes(), config.stat().st_mtime_ns, backups(config)
    monkeypatch.setattr(
        owner, "private_file", lambda *args: pytest.fail("Idempotency wrote a file")
    )
    assert owner.register(*files)["status"] == "already_registered"
    assert (config.read_bytes(), config.stat().st_mtime_ns, backups(config)) == before


@pytest.mark.parametrize(
    "field,replacement", [("command", '"other"'), ("startup_timeout_sec", "true")]
)
def test_different_existing_entry_refused_without_change(files, field, replacement):
    owner.register(*files)
    config = files[2]
    lines = config.read_text().splitlines()
    selected_start = lines.index(f"[mcp_servers.{owner.SERVER}]")
    line = next(
        i for i, value in enumerate(lines) if value.startswith(f"{field} = ") and i > selected_start
    )
    lines[line] = f"{field} = {replacement}"
    config.write_text("\n".join(lines))
    before, saved = config.read_bytes(), backups(config)
    with pytest.raises(owner.RegistrationError, match="different_existing_entry_refused"):
        owner.register(*files)
    assert config.read_bytes() == before and backups(config) == saved


def test_changed_configuration_before_publication_is_retained(files, monkeypatch):
    config = files[2]
    newer = ORIGINAL + b"\n# Concurrent editor's original work\n"
    original_writer = owner.private_file

    def write_then_edit(path, value):
        original_writer(path, value)
        if path.suffix == ".stage":
            config.write_bytes(newer)

    monkeypatch.setattr(owner, "private_file", write_then_edit)
    with pytest.raises(owner.RegistrationError, match="configuration_changed_before_publication"):
        owner.register(*files)
    assert config.read_bytes() == newer
    assert backups(config)[0].read_bytes() == ORIGINAL
    assert not list(config.parent.glob("*.stage"))


@pytest.mark.parametrize("which", [0, 1, 2])
def test_missing_interpreter_artifact_or_config_refused_before_writes(files, which):
    files[which].unlink()
    with pytest.raises(OSError):
        owner.register(*files)
    assert not backups(files[2])


@pytest.mark.parametrize("content", [b"[broken", b"mcp_servers = 1", b"mcp_servers = {}"])
def test_invalid_or_nonappendable_configuration_refused_without_change(files, content):
    config = files[2]
    config.write_bytes(content)
    with pytest.raises(owner.RegistrationError):
        owner.register(*files)
    assert config.read_bytes() == content and not backups(config)


def test_oversized_config_refused_without_rewrite(files):
    config = files[2]
    content = b"#" + b"x" * owner.MAX_CONFIG_BYTES
    config.write_bytes(content)
    with pytest.raises(owner.RegistrationError, match="configuration_size_refused"):
        owner.register(*files)
    assert config.read_bytes() == content and not backups(config)


@pytest.mark.parametrize("which", [0, 1, 2, "parent"])
def test_reparse_observation_refused_before_writes(files, monkeypatch, which):
    target = files[2].parent if which == "parent" else files[which]
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
        return value

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(owner.RegistrationError, match="redirected_path_refused"):
        owner.register(*files)
    assert files[2].read_bytes() == ORIGINAL and not backups(files[2])


def test_symlink_observation_refused_without_following(files, monkeypatch):
    target = files[1]
    original = Path.lstat

    def linked(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return (
            SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0) if path == target else value
        )

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(owner.RegistrationError, match="redirected_path_refused"):
        owner.register(*files)
    assert files[2].read_bytes() == ORIGINAL and not backups(files[2])


def test_failed_publish_retains_original_and_private_backup(files, monkeypatch):
    def fail(*args):
        raise OSError("FIXTURE_SECRET_DO_NOT_PRINT")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        owner.register(*files)
    assert files[2].read_bytes() == ORIGINAL
    assert backups(files[2])[0].read_bytes() == ORIGINAL
    assert not list(files[2].parent.glob("*.stage"))


def test_postpublication_change_is_unknown_and_never_restored(files, monkeypatch):
    config = files[2]
    newer = ORIGINAL + b"\n# A different owner changed the published configuration\n"
    replace = os.replace

    def publish_then_edit(source, target):
        replace(source, target)
        config.write_bytes(newer)

    monkeypatch.setattr(os, "replace", publish_then_edit)
    with pytest.raises(owner.RegistrationError, match="registration_acknowledgment_unknown"):
        owner.register(*files)
    assert config.read_bytes() == newer
    assert backups(config)[0].read_bytes() == ORIGINAL


def test_existing_backup_name_cannot_be_overwritten(files, monkeypatch):
    config = files[2]
    occupied = config.with_name(f".{config.name}.qtrades-fixturecollision.backup")
    occupied.write_bytes(b"Existing fixture backup must survive")
    monkeypatch.setattr(owner.uuid, "uuid4", lambda: SimpleNamespace(hex="fixturecollision"))
    with pytest.raises(FileExistsError):
        owner.register(*files)
    assert occupied.read_bytes() == b"Existing fixture backup must survive"
    assert config.read_bytes() == ORIGINAL


@pytest.mark.parametrize("which", [0, 1, 2])
def test_directory_interpreter_artifact_or_config_is_not_a_regular_file(files, which):
    files[which].unlink()
    files[which].mkdir()
    with pytest.raises(owner.RegistrationError, match="regular_file_required"):
        owner.register(*files)
    assert not backups(files[2])


def test_main_never_prints_unrelated_secrets_on_success_or_parse_failure(files, capsys):
    interpreter, artifact, config = files
    argv = ["--python", str(interpreter), "--artifact", str(artifact), "--config", str(config)]
    assert owner.main(argv) == 0
    output = capsys.readouterr()
    assert "FIXTURE_SECRET_DO_NOT_PRINT" not in output.out + output.err
    assert json.loads(output.out)["status"] == "registered"
    config.write_bytes(b'invalid = "FIXTURE_SECRET_DO_NOT_PRINT')
    assert owner.main(argv) == 1
    output = capsys.readouterr()
    assert not output.out and "FIXTURE_SECRET_DO_NOT_PRINT" not in output.err
    assert json.loads(output.err)["reason"] == "configuration_parse_refused"


def test_main_does_not_print_raw_filesystem_error(files, monkeypatch, capsys):
    def fail(*args):
        raise OSError("FIXTURE_SECRET_DO_NOT_PRINT")

    monkeypatch.setattr(owner, "register", fail)
    argv = ["--python", str(files[0]), "--artifact", str(files[1]), "--config", str(files[2])]
    assert owner.main(argv) == 1
    output = capsys.readouterr()
    assert not output.out and "FIXTURE_SECRET_DO_NOT_PRINT" not in output.err
    assert json.loads(output.err)["reason"] == "filesystem_operation_failed"
