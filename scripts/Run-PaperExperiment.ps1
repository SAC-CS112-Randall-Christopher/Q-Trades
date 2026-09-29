[CmdletBinding()]
param([string] $RuntimeRoot)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$dataRoot = if ($RuntimeRoot) { (Resolve-Path -LiteralPath $RuntimeRoot).Path } else { $projectRoot }
$dataPath = Join-Path $dataRoot 'data'
if ($RuntimeRoot -and -not (Test-Path -LiteralPath $dataPath -PathType Container)) {
    throw 'Existing paper data is missing; no fresh installation was created.'
}
$serveArguments = '-m trading serve --experiment'
if ($RuntimeRoot) {
    if ($dataRoot.Contains('"')) { throw 'Invalid runtime path.' }
    $RuntimeRoot = $dataRoot
    $serveArguments += ' --runtime-root "' + $dataRoot + '"'
}
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runnerLog = Join-Path $dataPath 'supervisor.log'
$mutex = New-Object Threading.Mutex($false, 'Local\TradingResearchPaper20260927')
$hasLock = $false
$serverProcess = $null
. (Join-Path $PSScriptRoot 'PaperProcessOwnership.ps1')

function Write-RunnerLog([string] $message) {
    "$(Get-Date -Format o) $message" | Add-Content -LiteralPath $runnerLog -Encoding UTF8
}

function Stop-OwnedServer {
    if ($null -eq $script:serverProcess) { return }
    $parent = $script:serverProcess.Id
    $identity = Get-CimInstance Win32_Process -Filter "ProcessId=$parent"
    $pidRecord = Get-Item -LiteralPath (Join-Path $dataPath 'server.pid') -ErrorAction SilentlyContinue
    if (-not $identity) { $script:serverProcess = $null; return }
    if (-not $pidRecord -or -not (Test-PaperLauncherIdentity $identity $pythonPath $pidRecord.LastWriteTimeUtc $RuntimeRoot)) {
        Write-RunnerLog 'Launcher identity changed; preserving the unverified process.'
        $script:serverProcess = $null
        return
    }
    # The venv launcher may own a Python child. Stop only this launcher and its verified child.
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$parent" |
        Where-Object { Test-PaperWorkerIdentity $_ $identity $RuntimeRoot }
    foreach ($child in $children) {
        Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
    }
    if (-not $script:serverProcess.HasExited) {
        Stop-Process -Id $parent -ErrorAction SilentlyContinue
    }
    $script:serverProcess = $null
}

try {
    try { $hasLock = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $hasLock = $true }
    if (-not $hasLock) { exit 0 }
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Project Python environment is missing.' }
    New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
    $PID | Set-Content -LiteralPath (Join-Path $dataPath 'supervisor.pid')
    Set-Location -LiteralPath $projectRoot
    Write-RunnerLog 'Supervisor started; local paper experiment only.'
    while ($true) {
        try {
            $databaseStart = Start-Process -FilePath 'docker.exe' `
                -ArgumentList @('compose', 'up', '-d', '--wait', '--wait-timeout', '30', 'paper-db') `
                -WorkingDirectory $dataRoot -WindowStyle Hidden -PassThru -Wait `
                -RedirectStandardOutput (Join-Path $dataPath 'database-start.out.log') `
                -RedirectStandardError (Join-Path $dataPath 'database-start.err.log')
            if ($databaseStart.ExitCode -ne 0) { throw 'Dedicated paper database is unavailable.' }
            $listener = @(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue)
            if ($listener.Count) {
                $serverProcess = Get-ExistingPaperServer $pythonPath (Join-Path $dataPath 'server.pid') $listener $RuntimeRoot
                Write-RunnerLog "Adopted verified existing paper service launcher $($serverProcess.Id); no worker restart."
            } else {
                $runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList $serveArguments `
                    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput (Join-Path $dataPath "server-$runStamp.out.log") `
                    -RedirectStandardError (Join-Path $dataPath "server-$runStamp.err.log")
                $serverProcess.Id | Set-Content -LiteralPath (Join-Path $dataPath 'server.pid')
                Write-RunnerLog "Started paper service launcher $($serverProcess.Id)."
            }
            $failedHealth = 0
            while (-not $serverProcess.HasExited) {
                Start-Sleep -Seconds 20
                try {
                    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8780/api/health' -TimeoutSec 7
                    if ($health.paper -ne 'running') { throw 'Paper worker is stopped.' }
                    $failedHealth = 0
                } catch {
                    $failedHealth++
                    Write-RunnerLog "Paper health check failed ($failedHealth of 3)."
                    if ($failedHealth -ge 3) { throw 'Paper service did not recover; restarting owned worker.' }
                }
            }
            Write-RunnerLog 'Paper service exited; waiting before restart.'
        } catch {
            Write-RunnerLog $_.Exception.Message
        } finally {
            Stop-OwnedServer
        }
        Start-Sleep -Seconds 30
    }
} finally {
    Stop-OwnedServer
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
