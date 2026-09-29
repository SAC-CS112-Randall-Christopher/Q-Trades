[CmdletBinding()]
param([switch] $CheckOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$taskName = 'TradingResearch-Paper-20260927'
$dashboardUrl = 'http://127.0.0.1:8780/#experiment'
$healthUrl = 'http://127.0.0.1:8780/api/health'
$runnerPath = Join-Path $PSScriptRoot 'Run-PaperExperiment.ps1'
$logPath = Join-Path $projectRoot 'data\desktop-launcher.log'

function Write-LauncherLog([string] $Message) {
    # This operational log contains no model prompts, market payloads or credentials.
    if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 1MB) {
        $archivePath = Join-Path $projectRoot ('data\desktop-launcher-' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff') + '.log')
        # Both fixed paths are inside this project's data folder. Preserve the old log.
        Move-Item -LiteralPath $logPath -Destination $archivePath
    }
    "$(Get-Date -Format o) $Message" | Add-Content -LiteralPath $logPath -Encoding UTF8
}

function Get-OwnedStartupTask {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if (-not (Test-PaperStartupAction -Task $task -ProjectRoot $projectRoot)) {
        throw 'The startup task does not match this project. No task was changed or started.'
    }
    if ($task.State -eq 'Disabled') {
        throw 'The project startup task is disabled. Enable TradingResearch-Paper-20260927 in Task Scheduler to use automatic startup.'
    }
    return $task
}

function Test-LocalDashboard {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3 -MaximumRedirection 0
        return ($health.service -eq 'running' -and $health.mode -eq 'paper')
    } catch {
        return $false
    }
}

try {
    foreach ($required in @($runnerPath, (Join-Path $projectRoot '.venv\Scripts\python.exe'),
        (Join-Path $projectRoot 'apps\web\dist\index.html'))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "A required application file is missing: $required"
        }
    }
    $task = Get-OwnedStartupTask
    $available = Test-LocalDashboard

    if ($CheckOnly) {
        [ordered]@{
            project = $projectRoot
            url = $dashboardUrl
            task = $taskName
            task_state = $task.State.ToString()
            task_matches_project = $true
            dashboard_available = $available
            action = 'Read-only check; no task start or browser launch'
        } | ConvertTo-Json -Compress
        if ($available) { exit 0 }
        exit 2
    }

    if (-not $available) {
        if ($task.State -ne 'Running') {
            # Reuse the registered, limited-privilege task and its single-owner guard.
            # Never register a replacement, stop a process, or create a second worker.
            Start-ScheduledTask -InputObject $task
            Write-LauncherLog 'Requested start of the verified project startup task.'
        } else {
            Write-LauncherLog 'Waiting for the existing supervisor to make the dashboard available.'
        }
        $deadline = [DateTime]::UtcNow.AddSeconds(90)
        do {
            Start-Sleep -Seconds 2
            $available = Test-LocalDashboard
        } while (-not $available -and [DateTime]::UtcNow -lt $deadline)
    }

    if (-not $available) {
        throw "The local dashboard did not become available. Make sure Docker Desktop is running, then try again. Details: $projectRoot\data\supervisor.log. The existing task has not been stopped."
    }
    # A visible default-browser window is the explicitly requested user interface.
    Start-Process -FilePath $dashboardUrl
    Write-LauncherLog 'Opened the local paper dashboard in the default browser.'
    exit 0
} catch {
    $message = $_.Exception.Message
    if (-not $CheckOnly) {
        try { Write-LauncherLog "Unable to open dashboard: $message" } catch { }
    }
    [Console]::Error.WriteLine($message)
    exit 1
}
