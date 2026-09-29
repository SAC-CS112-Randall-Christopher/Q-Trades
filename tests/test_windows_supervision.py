import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows runtime stop guard")
@pytest.mark.parametrize("process_name", ["python.exe", "pythonw.exe"])
def test_stop_runtime_refuses_active_console_or_windowless_jobs(tmp_path, process_name):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "data").mkdir()
    shutil.copy2(root / "scripts/Stop-ResearchRuntime.ps1", scripts / "Stop-ResearchRuntime.ps1")
    (tmp_path / "data/research-runtime.json").write_text(
        json.dumps({"origin": "http://127.0.0.1:11435"}), encoding="utf-8"
    )
    driver = tmp_path / "assert-stop-guard.ps1"
    driver.write_text(
        r"""param([string] $ProcessName)
$ErrorActionPreference = 'Stop'
$testRoot = $PSScriptRoot
function Get-ScheduledTask {
    $runner = Join-Path $testRoot 'scripts\Run-ResearchRuntime.ps1'
    [pscustomobject]@{Actions=@([pscustomobject]@{
        Execute='powershell.exe'; WorkingDirectory=$testRoot
        Arguments=('-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"')
    })}
}
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($Filter) { throw 'Guard must reject before looking up a server process' }
    [pscustomobject]@{Name=$ProcessName; CommandLine='python -m scripts.run_qualification_queue'}
}
function Stop-ScheduledTask { throw 'MUST NOT stop any task' }
function Stop-Process { throw 'MUST NOT stop any process' }
try {
    & (Join-Path $testRoot 'scripts\Stop-ResearchRuntime.ps1')
    throw 'Active job was not protected'
} catch {
    if ($_.Exception.Message -ne
        'A research job is active; preserve it and finish it before stopping the runtime.') {
        throw
    }
    Write-Output 'Active job protected'
}
""",
        encoding="utf-8",
    )
    shell = shutil.which("powershell.exe")
    assert shell
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(driver), process_name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Active job protected" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console lifetime contract")
@pytest.mark.parametrize("exit_code", [0, 7])
def test_windowless_service_preserves_logs_and_child_exit(tmp_path, exit_code):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(root / "scripts/service_host.py", scripts / "service_host.py")
    # A disposable supervisor exercises the real host without touching project services.
    (scripts / "Run-PaperExperiment.ps1").write_text(
        """$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices;
public static class ConsoleProbe {
[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
}'
$hasConsole = [ConsoleProbe]::GetConsoleWindow() -ne [IntPtr]::Zero
[pscustomobject]@{has_console=$hasConsole} | ConvertTo-Json -Compress
[Console]::Error.WriteLine('retained child diagnostic')
"""
        + f"exit {exit_code}\n",
        encoding="utf-8",
    )
    executable = Path(sys.executable).with_name("pythonw.exe")
    assert executable.is_file()
    child = subprocess.Popen([str(executable), str(scripts / "service_host.py"), "--kind", "paper"])
    assert child.wait(timeout=30) == exit_code
    state = json.loads((tmp_path / "data/service-host-paper.json").read_text(encoding="utf-8"))
    assert state["state"] == "exited"
    assert state["exit_code"] == exit_code
    assert state["host_has_console"] is False
    outputs = list((tmp_path / "data").glob("*.out.log"))
    errors = list((tmp_path / "data").glob("*.err.log"))
    assert len(outputs) == len(errors) == 1
    assert json.loads(outputs[0].read_text(encoding="utf-8"))["has_console"] is False
    assert "retained child diagnostic" in errors[0].read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership contract")
def test_paper_adoption_rejects_foreign_and_reused_process_ids(tmp_path):
    shell = shutil.which("powershell.exe")
    assert shell
    script = tmp_path / "assert-ownership.ps1"
    script.write_text(
        r"""
$ErrorActionPreference = 'Stop'
. ./scripts/PaperProcessOwnership.ps1
$exe = 'C:\project\.venv\Scripts\python.exe'
$start = [DateTime]'2026-09-28T14:24:00Z'
$launcher = [pscustomobject]@{
    ProcessId=7; ExecutablePath=$exe; CreationDate=$start
    CommandLine=('"'+$exe+'" -m trading serve --experiment')
}
if (-not (Test-PaperLauncherIdentity $launcher $exe $start.AddSeconds(1))) {
    throw 'Valid launcher rejected'
}
if (Test-PaperLauncherIdentity $launcher $exe $start.AddSeconds(31)) {
    throw 'Stale PID receipt accepted'
}
if (Test-PaperLauncherIdentity $launcher $exe $start.AddSeconds(-1)) { throw 'Reused PID accepted' }
if (Test-PaperLauncherIdentity $launcher 'C:\other\python.exe' $start.AddSeconds(1)) {
    throw 'Foreign executable accepted'
}
$launcher.CommandLine += ' --port 9000'
if (Test-PaperLauncherIdentity $launcher $exe $start.AddSeconds(1)) {
    throw 'Foreign command accepted'
}
$worker = [pscustomobject]@{
    Name='python.exe'; ParentProcessId=7; ExecutablePath='C:\Python\python.exe'
    CreationDate=$start.AddMilliseconds(50)
    CommandLine='"C:\Python\python.exe" -m trading serve --experiment'
}
if (-not (Test-PaperWorkerIdentity $worker $launcher)) { throw 'Base interpreter child rejected' }
$worker.ParentProcessId = 8
if (Test-PaperWorkerIdentity $worker $launcher) { throw 'Foreign parent accepted' }
$worker.ParentProcessId = 7
$worker.CreationDate = $start.AddSeconds(31)
if (Test-PaperWorkerIdentity $worker $launcher) { throw 'Unexpected late child accepted' }
Write-Output 'Ownership checks passed'
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert "Ownership checks passed" in result.stdout
