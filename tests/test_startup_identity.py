"""Windows-only exact startup contracts; the fixture never starts or stops a task."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows scheduled-task action contract")
def test_launcher_accepts_current_pythonw_host_and_preserves_foreign_actions(tmp_path):
    script = tmp_path / "startup-contract.ps1"
    script.write_text(
        r"""
$ErrorActionPreference = 'Stop'
. ./scripts/PaperStartupIdentity.ps1
$root = 'C:\trading-app'
$action = [pscustomobject]@{
    Execute='C:\trading-app\.venv\Scripts\pythonw.exe'
    Arguments='"C:\trading-app\scripts\service_host.py" --kind paper'
    WorkingDirectory=$root
}
$task = [pscustomobject]@{ Actions=@($action) }
if (-not (Test-PaperStartupAction $task $root)) { throw 'Current host rejected' }
$action.Arguments += ' --unexpected'
if (Test-PaperStartupAction $task $root) { throw 'Foreign arguments accepted' }
$action.Execute='powershell.exe'
$action.Arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "' +
    'C:\trading-app\scripts\Run-PaperExperiment.ps1"'
if (-not (Test-PaperStartupAction $task $root)) { throw 'Legacy host rejected' }
$action.WorkingDirectory='C:\other-app'
if (Test-PaperStartupAction $task $root) { throw 'Foreign project accepted' }
$task.Actions=@($action,$action)
if (Test-PaperStartupAction $task $root) { throw 'Multiple actions accepted' }
Write-Output 'Exact task identities passed; no process or task was changed'
""",
        encoding="utf-8",
    )
    shell = shutil.which("powershell.exe")
    assert shell
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
