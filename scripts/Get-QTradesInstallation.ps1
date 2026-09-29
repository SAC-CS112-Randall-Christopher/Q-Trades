[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')
$taskName = 'TradingResearch-Paper-20260927'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
$actions = @($task.Actions)
if ($actions.Count -ne 1 -or -not $actions[0].WorkingDirectory) {
    throw 'Startup task has an unexpected action; no files or services were changed.'
}
$root = $actions[0].WorkingDirectory
$matches = Test-PaperStartupAction -Task $task -ProjectRoot $root
if (-not $matches) { throw 'Startup command does not match Q-Trades; preserve and inspect it.' }
# Inspect the single existing paper listener; never enumerate unrelated commands or credentials.
$listeners = @(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue)
[ordered]@{
    task = $taskName
    task_state = $task.State.ToString()
    runtime_root = $root
    startup_matches = $matches
    source_checkout = (Split-Path -Parent $PSScriptRoot)
    same_as_source_checkout = ($root.TrimEnd('\') -ieq (Split-Path -Parent $PSScriptRoot).TrimEnd('\'))
    monitor_data_exists = (Test-Path -LiteralPath (Join-Path $root 'data\monitor.sqlite3') -PathType Leaf)
    paper_settings_exist = (Test-Path -LiteralPath (Join-Path $root 'data\paper-database.json') -PathType Leaf)
    listener_pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    listener_ownership = 'Not established by port alone; validate before stopping any process'
    action = 'Read-only inspection; no credential contents, task changes, or restarts'
} | ConvertTo-Json -Depth 4
