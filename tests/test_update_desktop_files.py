"""Exercise actual copy/restore code only on temporary synthetic launcher files."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SHELL = (
    os.environ.get("QTRADES_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")
)
pytestmark = pytest.mark.skipif(not SHELL, reason="PowerShell is unavailable")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def desktop(tmp_path):
    runtime, old, new = (tmp_path / n for n in ("runtime", "old code", "new code"))
    for path in (
        runtime / "data/update-receipts",
        old / "data/desktop-launcher-build",
        new / "scripts",
        tmp_path / "fake desktop",
    ):
        path.mkdir(parents=True)
    old_file = old / "data/desktop-launcher-build/Trading Research.exe"
    old_file.write_bytes(b"synthetic prior launcher; never executed")
    screen = tmp_path / "fake desktop/Trading Research.exe"
    screen.write_bytes(old_file.read_bytes())
    new_file = new / "new.exe"
    new_file.write_bytes(b"synthetic new launcher; never executed")
    (new / "scripts/Build-DesktopLauncher.ps1").write_text(
        "param([string] $RuntimeRoot)\n@{Executable=(Join-Path "
        "(Split-Path $PSScriptRoot -Parent) 'new.exe')} | ConvertTo-Json\n"
    )
    text = (ROOT / "scripts/QTradesNativeUpdate.ps1").read_text()
    marker = "([Environment]::GetFolderPath('Desktop'))"
    assert text.count(marker) == 1
    # Replace only native Desktop resolution, never target the operator's real desktop.
    text = text.replace(marker, "(Join-Path $PSScriptRoot 'fake desktop')")
    script = tmp_path / "native.ps1"
    script.write_text(text)
    for name in ("PaperStartupIdentity.ps1", "PaperProcessOwnership.ps1"):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / name)
    plan = {
        "runtime_root": str(runtime),
        "old_root": str(old),
        "target_root": str(new),
        "id": "a" * 32,
    }

    def run(action):
        request = tmp_path / "request.json"
        request.write_text(json.dumps(plan))
        return subprocess.run(
            [
                SHELL,
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script),
                "-Action",
                action,
                "-Request",
                str(request),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    result = run("prepare_desktop")
    assert result.returncode == 0, result.stderr
    plan["desktop"] = json.loads(result.stdout)
    return run, screen, old_file, new_file, plan


def test_launcher_replacement_and_recovery_preserve_original_bytes(desktop):
    run, screen, old, new, _ = desktop
    assert screen.read_bytes() == old.read_bytes()
    assert run("install_desktop").returncode == 0
    assert screen.read_bytes() == new.read_bytes()
    assert run("restore_desktop").returncode == 0
    assert screen.read_bytes() == old.read_bytes()
    assert run("restore_desktop").returncode == 0  # Idempotent restoration.


def test_changed_desktop_file_is_not_overwritten(desktop):
    run, screen, _, _, _ = desktop
    screen.write_bytes(b"unrelated replacement")
    assert run("install_desktop").returncode != 0
    assert screen.read_bytes() == b"unrelated replacement"
    assert run("restore_desktop").returncode != 0
    assert screen.read_bytes() == b"unrelated replacement"


def test_changed_backup_is_not_used_for_recovery(desktop):
    run, screen, _, new, plan = desktop
    assert run("install_desktop").returncode == 0
    Path(plan["desktop"]["backup"]).write_bytes(b"not the saved launcher")
    assert run("restore_desktop").returncode != 0
    assert screen.read_bytes() == new.read_bytes()


def test_changed_new_launcher_is_not_installed(desktop):
    run, screen, old, new, _ = desktop
    new.write_bytes(b"changed after preparation")
    assert run("install_desktop").returncode != 0
    assert screen.read_bytes() == old.read_bytes()
