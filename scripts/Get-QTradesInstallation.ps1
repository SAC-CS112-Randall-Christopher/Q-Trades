[CmdletBinding()]
param([string] $ExpectedRuntimeRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')
. (Join-Path $PSScriptRoot 'PaperProcessOwnership.ps1')
# Health observations are tri-state: reported true, reported false, or unknown.
# A text/missing response is not evidence that the account stopped or lost balance.
function Get-QTradesReportedBoolean {
    param($Object, [string] $Name)
    if ($Object -isnot [pscustomobject]) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $property.Value -isnot [bool]) { return $null }
    return $property.Value
}

function ConvertTo-QTradesPaperHealth {
    param($Response)
    if ($Response -is [string]) {
        if ($Response.Length -gt 4000000 -or -not $Response.TrimStart().StartsWith('{')) {
            throw 'Status response is not a bounded JSON object.'
        }
        # Some hosts return the body as text. Parse it explicitly, never coerce it.
        $Response = ConvertFrom-Json -InputObject $Response -ErrorAction Stop
    }
    if ($Response -isnot [pscustomobject] -or $Response.paper -isnot [pscustomobject]) {
        throw 'Paper status object is missing or invalid.'
    }
    $paper = $Response.paper
    $result = [ordered]@{
        paper_enabled = (Get-QTradesReportedBoolean $paper 'enabled')
        paper_running = (Get-QTradesReportedBoolean $paper 'running')
        paper_stale = (Get-QTradesReportedBoolean $paper 'stale')
        journal_balanced = (Get-QTradesReportedBoolean $paper.journal 'balanced')
        reported_engine_error = $null
    }
    $errorProperty = $paper.PSObject.Properties['error']
    if ($null -ne $errorProperty) {
        if ($null -eq $errorProperty.Value) { $result.reported_engine_error = $false }
        elseif ($errorProperty.Value -is [string]) {
            $result.reported_engine_error = ($errorProperty.Value.Length -gt 0)
        }
    }
    $unknown = @($result.Keys | Where-Object { $null -eq $result[$_] })
    $result['complete'] = ($unknown.Count -eq 0)
    $result['unknown_fields'] = $unknown
    return $result
}

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
        # Windows PowerShell's case-insensitive JSON objects reject retained exchange
        # keys such as e/E. Reuse the Python updater's bounded, no-proxy/no-redirect
        # reader, then parse only a small health projection without exchange payloads.
        $python = Join-Path $codeRoot '.venv\Scripts\python.exe'
        $reply = @(& $python -B (Join-Path $PSScriptRoot 'qtrades_health.py') 2>$null)
        if ($LASTEXITCODE -ne 0) { throw 'Local health projection failed.' }
        $health = ConvertTo-QTradesPaperHealth ($reply -join "`n")
        if (-not $health.complete) {
            $healthError = 'Some health fields are missing or invalid; null means unknown, not failed.'
        }
    } catch {
        $healthError = 'Paper health could not be read or parsed; account health is unknown. No restart.'
    }
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
    activation = 'Explicit Activate/Recover commands are available; this inspection never applies them'
    action = 'Read-only inspection; no credentials, task changes, financial writes, or restarts'
} | ConvertTo-Json -Depth 4
