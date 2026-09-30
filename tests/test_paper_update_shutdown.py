"""Windows ownership checks and a real disposable detached paper process tree."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership")


@pytest.mark.parametrize(
    "variant,accepted",
    [
        ("host", True),
        ("legacy", True),
        ("models", False),
        ("other_root", False),
        ("extra_command", False),
        ("foreign_executable", False),
    ],
)
def test_supervisor_identity_does_not_accept_foreign_work(tmp_path, variant, accepted):
    driver = tmp_path / "identity.ps1"
    driver.write_text(
        r"""param($Helper,$Root,$Variant)
$ErrorActionPreference='Stop'
. $Helper
$shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runner=Join-Path $Root 'scripts\Run-PaperExperiment.ps1'
$command='"'+$shell+'" -NoProfile -NonInteractive -File "'+$runner+'"'
if($Variant -eq 'legacy'){
    $command='powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File "'+$runner+'"'
}
if($Variant -eq 'models'){
    $command=$command.Replace('Run-PaperExperiment.ps1','Run-ResearchRuntime.ps1')
}
if($Variant -eq 'other_root'){$command=$command.Replace($Root,$Root+'-other')}
if($Variant -eq 'extra_command'){$command+=' -Command whoami'}
if($Variant -eq 'foreign_executable'){$shell='C:\foreign\powershell.exe'}
$candidate=[pscustomobject]@{ExecutablePath=$shell;CommandLine=$command}
Test-PaperSupervisorIdentity $candidate $Root | ConvertTo-Json
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(driver),
            str(ROOT / "scripts/PaperUpdateShutdown.ps1"),
            str(tmp_path / "paper workspace"),
            variant,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is accepted


def test_detached_tree_stops_only_owned_processes_and_rejects_changed_identity(tmp_path):
    runtime = tmp_path / "paper workspace"
    for name in ("data", "scripts", ".venv/Scripts", "trading"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(sys.executable, runtime / ".venv/Scripts/python.exe")
    (runtime / ".venv/pyvenv.cfg").write_text(
        f"home = {sys.base_prefix}\ninclude-system-site-packages = false\n", encoding="utf-8"
    )
    (runtime / "trading/__init__.py").write_text("", encoding="utf-8")
    (runtime / "trading/__main__.py").write_text(
        "import os,time\nfrom pathlib import Path\n"
        "Path('data/worker-ready.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    runner = runtime / "scripts/Run-PaperExperiment.ps1"
    runner.write_text(
        r"""$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$PID | Set-Content -LiteralPath (Join-Path $root 'data/supervisor.pid')
$python=Join-Path $root '.venv/Scripts/python.exe'
$child=Start-Process -FilePath $python -ArgumentList '-m trading serve --experiment' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru
$child.Id | Set-Content -LiteralPath (Join-Path $root 'data/server.pid')
Wait-Process -Id $child.Id
""",
        encoding="utf-8",
    )
    driver = tmp_path / "stop-tree.ps1"
    driver.write_text(
        r"""param($Helper,$Root,$ForeignId)
$ErrorActionPreference='Stop'
. $Helper
$owned=@(Get-PaperUpdateProcessSnapshot $Root)
if($owned.Count -ne 3){throw 'Expected supervisor, base worker and venv launcher'}
if($owned.ProcessId -contains [int]$ForeignId){throw 'Foreign process was captured'}
$record=Get-Item -LiteralPath (Join-Path $Root 'data/server.pid')
$originalId=(Get-Content -LiteralPath $record.FullName -Raw).Trim()
$originalTime=$record.LastWriteTimeUtc
$foreign=Get-CimInstance Win32_Process -Filter "ProcessId=$ForeignId"
[IO.File]::WriteAllText($record.FullName,[string]$ForeignId)
[IO.File]::SetLastWriteTimeUtc($record.FullName,([DateTime]$foreign.CreationDate).ToUniversalTime())
try{Get-PaperUpdateProcessSnapshot $Root;throw 'Foreign PID record was accepted'}
catch{
    if($_.Exception.Message -ne
        'Recorded launcher is not this paper runtime; preserving it.'){throw}
}finally{
    [IO.File]::WriteAllText($record.FullName,$originalId)
    [IO.File]::SetLastWriteTimeUtc($record.FullName,$originalTime)
}
$changed=@($owned | Select-Object ProcessId,ExecutablePath,CommandLine,CreationDate)
$changed[0].CreationDate=([DateTime]$changed[0].CreationDate).AddSeconds(1)
try{Stop-VerifiedPaperUpdateProcesses $changed;throw 'Changed lifetime was not rejected'}
catch{
    if($_.Exception.Message -ne
        'Paper process identity changed during shutdown; preserving it.'){throw}
}
$missing=@($owned|Where-Object {
    -not (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue)
})
if($missing.Count){throw 'Mismatch stopped a process'}
Stop-VerifiedPaperUpdateProcesses $owned
Start-Sleep -Milliseconds 250
$remaining=@($owned|Where-Object {
    Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
})
if($remaining.Count){throw 'Owned process still running'}
if(-not (Get-Process -Id $ForeignId -ErrorAction SilentlyContinue)){
    throw 'Foreign process was stopped'
}
@{owned_count=$owned.Count;changed_identity_preserved=$true;
    foreign_preserved=$true;foreign_pid_record_rejected=$true}|
    ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    flags = subprocess.CREATE_NO_WINDOW
    foreign = subprocess.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(60)"], creationflags=flags
    )
    supervisor = subprocess.Popen(
        [SHELL, "-NoProfile", "-NonInteractive", "-File", str(runner)],
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        marker = runtime / "data/worker-ready.pid"
        while not marker.exists() and time.monotonic() < deadline:
            assert supervisor.poll() is None, "Disposable supervisor exited before worker startup"
            time.sleep(0.05)
        assert marker.exists(), "Disposable paper tree did not start"
        result = subprocess.run(
            [
                SHELL,
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(driver),
                str(ROOT / "scripts/PaperUpdateShutdown.ps1"),
                str(runtime),
                str(foreign.pid),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(result.stdout.splitlines()[-1])
        assert receipt == {
            "owned_count": 3,
            "changed_identity_preserved": True,
            "foreign_preserved": True,
            "foreign_pid_record_rejected": True,
        }
        assert foreign.poll() is None
        supervisor.wait(timeout=5)
    finally:
        # Recheck executable, command and lifetime before cleaning any recorded child.
        cleanup = tmp_path / "cleanup.ps1"
        cleanup.write_text(
            "param($Helper,$Root)\n$ErrorActionPreference='Stop'\n. $Helper\n"
            "Stop-VerifiedPaperUpdateProcesses @(Get-PaperUpdateProcessSnapshot $Root)\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                SHELL,
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(cleanup),
                str(ROOT / "scripts/PaperUpdateShutdown.ps1"),
                str(runtime),
            ],
            capture_output=True,
            timeout=15,
        )
        if supervisor.poll() is None:
            supervisor.terminate()
        if foreign.poll() is None:
            foreign.terminate()
        foreign.wait(timeout=5)
