"""Real disposable Git/robocopy on Windows; task, npm and Python operations are mocked."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("powershell.exe")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


DRIVER = r"""
param([string] $Source, [string] $Runtime, [string] $Scenario, [string] $Report)
$ErrorActionPreference='Stop'
$gitExe=(Get-Command git.exe).Source
$roboExe=(Get-Command robocopy.exe).Source
$global:operations=[Collections.Generic.List[string]]::new()
$global:running=$true
$global:enabled=$true
$python=Join-Path $Runtime '.venv/Scripts/python.exe'
function Get-ScheduledTask {
    $args='"'+(Join-Path $Runtime 'scripts/service_host.py')+'" --kind paper'
    if($Scenario -eq 'foreign_task'){$args+=' --other-project'}
    [pscustomobject]@{
        State=$(if($global:running){'Running'}else{'Ready'})
        Settings=[pscustomobject]@{Enabled=$global:enabled}
        Actions=@([pscustomobject]@{Execute=(Join-Path $Runtime '.venv/Scripts/pythonw.exe')
            Arguments=$args;WorkingDirectory=$Runtime})
    }
}
function Disable-ScheduledTask {$global:operations.Add('disable');$global:enabled=$false}
function Enable-ScheduledTask {$global:operations.Add('enable');$global:enabled=$true}
function Stop-ScheduledTask {
    $global:operations.Add('stop')
    if($Scenario -ne 'stop_failure'){$global:running=$false}
}
function Start-ScheduledTask {$global:operations.Add('start');$global:running=$true}
function Get-NetTCPConnection {if($global:running){[pscustomobject]@{LocalPort=8780}}}
function Start-Sleep {}
function git {
    if($args -contains 'get-url'){
        $global:LASTEXITCODE=0
        if($Scenario -eq 'wrong_remote'){return 'https://example.invalid/other.git'}
        return 'https://github.com/SAC-CS112-Randall-Christopher/Q-Trades.git'
    }
    & $gitExe @args
}
function npm {
    $global:operations.Add('build')
    $global:LASTEXITCODE=0
    if($Scenario -eq 'build_failure'){$global:LASTEXITCODE=1;return}
    if($args -contains 'build'){
        $dist=Join-Path $Source 'apps/web/dist'
        New-Item -ItemType Directory -Path $dist -Force|Out-Null
        [IO.File]::WriteAllText((Join-Path $dist 'index.html'),'compiled fixture')
        if($Scenario -eq 'changed_head'){git -C $Source commit --allow-empty -m 'concurrent change'|Out-Null}
    }
}
function robocopy {
    if(-not $args[0].StartsWith($PSScriptRoot) -or -not $args[1].StartsWith($PSScriptRoot)){
        throw 'Test copy escaped disposable directories'
    }
    $global:operations.Add('copy')
    & $roboExe @args
}
Set-Item -LiteralPath ('Function:\'+$python) -Value {
    $global:LASTEXITCODE=0
    if($args -contains 'pip'){
        $global:operations.Add('pip')
        if($Scenario -eq 'dependency_failure'){$global:LASTEXITCODE=1}
    }else{
        $global:operations.Add('health')
        if($Scenario -eq 'health_failure'){$global:LASTEXITCODE=2}
        '{"fixture":true}'
    }
}
& (Join-Path $Source 'scripts/Update-QTrades.ps1')
$code=$LASTEXITCODE
@{exit_code=$code;operations=@($global:operations.ToArray());running=$global:running;
  enabled=$global:enabled}|ConvertTo-Json|Set-Content $Report
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Real Windows robocopy with mocked task APIs")
@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "dirty",
        "diverged",
        "missing_main",
        "wrong_remote",
        "foreign_task",
        "changed_head",
        "build_failure",
        "stop_failure",
        "dependency_failure",
        "health_failure",
    ],
)
def test_manual_main_update_preserves_data_and_handles_failures(tmp_path, scenario):
    source, runtime = tmp_path / "source", tmp_path / "runtime"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Isolated test")
    git(source, "config", "user.email", "test@example.invalid")
    (source / ".gitignore").write_text("apps/web/dist/\napps/web/node_modules/\n")
    for relative in (
        "src/trading/api.py",
        "src/stale.py",
        "scripts/service_host.py",
        "apps/web/package.json",
        "requirements-lock.txt",
        "pyproject.toml",
        "README.md",
        "AGENTS.md",
        "scripts/qtrades_health.py",
    ):
        p = source / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("old fixture")
    for name in ("Update-QTrades.ps1", "PaperStartupIdentity.ps1"):
        text = (ROOT / "scripts" / name).read_text()
        # The actual supervisor mutex is never acquired by a test.
        text = text.replace(
            "Local\\TradingResearchPaper20260927", "Local\\QTradesTest" + tmp_path.name
        )
        text = text.replace(
            "Local\\QTradesManualUpdate", "Local\\QTradesUpdaterTest" + tmp_path.name
        )
        (source / "scripts" / name).write_text(text)
    git(source, "add", ".")
    git(source, "commit", "-m", "old")
    old = git(source, "rev-parse", "HEAD")
    shutil.copytree(source, runtime, ignore=shutil.ignore_patterns(".git"))
    protected = {
        "data/monitor.sqlite3": b"actual test sentinel, not a database",
        "data/paper-database.json": b"never read or copied",
        "data/private.env": b"private fixture",
        "docs/evidence/frozen.json": b"retained research fixture",
        "configs/paper.toml": b"operator configuration fixture",
        "compose.yaml": b"retained volume configuration",
        ".git/local-work": b"retained original git metadata",
        "apps/web/node_modules/keep.txt": b"retained local dependency fixture",
    }
    for relative, content in protected.items():
        p = runtime / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    exe = runtime / ".venv/Scripts/python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("Never executed: PowerShell mocks this command")
    (source / "src/trading/api.py").write_text("new fixture")
    (source / "src/stale.py").unlink()
    if scenario == "missing_main":
        (source / "src/trading/api.py").unlink()
    git(source, "add", "-A")
    git(source, "commit", "-m", "new main")
    target = git(source, "rev-parse", "HEAD")
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(bare)], check=True, capture_output=True
    )
    git(source, "remote", "add", "origin", str(bare))
    git(source, "checkout", "--detach", old)
    if scenario == "dirty":
        (source / "uncommitted.txt").write_text("preserve")
    if scenario == "diverged":
        (source / "local-only.txt").write_text("preserve this commit")
        git(source, "add", ".")
        git(source, "commit", "-m", "local work")
    before = git(source, "rev-parse", "HEAD")
    driver, report = tmp_path / "driver.ps1", tmp_path / "result.json"
    driver.write_text(DRIVER)
    result = subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-File",
            str(driver),
            str(source),
            str(runtime),
            scenario,
            str(report),
        ],
        text=True,
        capture_output=True,
        timeout=40,
    )
    assert report.is_file(), result.stdout + result.stderr
    outcome = json.loads(report.read_text(encoding="utf-8-sig"))
    ops = outcome["operations"]
    assert all((runtime / p).read_bytes() == b for p, b in protected.items())
    if scenario == "success":
        assert outcome["exit_code"] == 0, result.stdout + result.stderr
        assert (runtime / "src/trading/api.py").read_text() == "new fixture"
        assert not (runtime / "src/stale.py").exists()
        assert (runtime / "data/installed-commit.txt").read_text() == target
        backups = list((runtime / "data/update-backups").iterdir())
        assert len(backups) == 1
        assert (backups[0] / "src/stale.py").read_text() == "old fixture"
        assert not (backups[0] / "data").exists()
        assert ops.index("stop") < ops.index("pip") < ops.index("start")
    else:
        assert outcome["exit_code"] != 0, outcome
        assert "updated and running:" not in result.stdout
        if scenario not in {"dependency_failure", "health_failure"}:
            assert (runtime / "src/trading/api.py").read_text() == "old fixture"
            assert "pip" not in ops and "start" not in ops
        if scenario in {"dirty", "diverged", "wrong_remote", "foreign_task", "missing_main"}:
            assert "disable" not in ops
            assert git(source, "rev-parse", "HEAD") == before
        if scenario == "dependency_failure":
            assert not outcome["running"] and not outcome["enabled"]
            assert "start" not in ops
