[CmdletBinding()]
param([string] $ExpectedRuntimeRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')
. (Join-Path $PSScriptRoot 'PaperProcessOwnership.ps1')
$taskName = 'TradingResearch-Paper-20260927'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
$actions = @($task.Actions)
if ($actions.Count -ne 1 -or -not $actions[0].WorkingDirectory) {
    throw 'Startup task has an unexpected action; no files or services were changed.'
}
$codeRoot = $actions[0].WorkingDirectory
$root = if ($ExpectedRuntimeRoot) { $ExpectedRuntimeRoot } else { $codeRoot }
$managedRoot = if ($root.TrimEnd('\') -ine $codeRoot.TrimEnd('\')) { $root } else { '' }
$matches = Test-PaperStartupAction -Task $task -ProjectRoot $codeRoot -RuntimeRoot $managedRoot
if (-not $matches) { throw 'Startup command does not match Q-Trades; preserve and inspect it.' }
# Query only this installation's paper listener. Port or PID alone is not ownership.
$listeners = @(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue)
$ownership = 'No paper listener observed; running-worker ownership is not established'
$launcherId = $null
$health = $null
$healthError = $null
if ($listeners.Count) {
    try {
        $owned = Get-ExistingPaperServer (Join-Path $codeRoot '.venv\Scripts\python.exe') `
            (Join-Path $root 'data\server.pid') $listeners $managedRoot
        $launcherId = $owned.Id
        $ownership = 'Verified executable, command, launch-time receipt and listener ancestry'
    } catch {
        $ownership = 'Listener ownership could not be verified; no process was changed'
    }
}
if ($null -ne $launcherId) {
    try {
        $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8780/api/status' `
            -TimeoutSec 5 -MaximumRedirection 0 -ErrorAction Stop
        $health = [ordered]@{
            paper_running = ($status.paper.running -eq $true)
            paper_stale = ($status.paper.stale -ne $false)
            journal_balanced = ($status.paper.journal.balanced -eq $true)
            reported_engine_error = [bool]$status.paper.error
        }
    } catch { $healthError = 'Current paper health could not be read; no service was restarted' }
}
[ordered]@{
    inspected_at = (Get-Date).ToUniversalTime().ToString('o')
    task = $taskName
    task_state = $task.State.ToString()
    runtime_root = $root
    code_root = $codeRoot
    startup_matches = $matches
    source_checkout = (Split-Path -Parent $PSScriptRoot)
    same_as_source_checkout = ($codeRoot.TrimEnd('\') -ieq (Split-Path -Parent $PSScriptRoot).TrimEnd('\'))
    monitor_data_exists = (Test-Path -LiteralPath (Join-Path $root 'data\monitor.sqlite3') -PathType Leaf)
    paper_settings_exist = (Test-Path -LiteralPath (Join-Path $root 'data\paper-database.json') -PathType Leaf)
    listener_pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    verified_launcher_pid = $launcherId
    listener_ownership = $ownership
    current_health = $health
    health_error = $healthError
    activation = 'Not connected; this receipt does not authorize a restart or deployment'
    action = 'Read-only inspection; no credentials, task changes, financial writes, or restarts'
} | ConvertTo-Json -Depth 4
