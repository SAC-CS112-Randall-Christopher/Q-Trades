[CmdletBinding()]
param(
    [ValidateSet('Verify','Check','Prepare','Activate','Recover')][string] $Action='Check',
    [Parameter(Mandatory=$true)][string] $RuntimeRoot,
    [switch] $Apply
)
$ErrorActionPreference='Stop'
$source=(Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$runtime=(Resolve-Path -LiteralPath $RuntimeRoot).Path
$python=Join-Path $runtime '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Existing project Python is unavailable. Nothing was installed.'
}
if ($Apply -and $Action -notin @('Activate','Recover')) { throw '-Apply is only for Activate or Recover.' }
Push-Location $source
try {
    if ($Action -eq 'Verify') {
        & (Join-Path $PSScriptRoot 'Get-QTradesInstallation.ps1') -ExpectedRuntimeRoot $runtime
        & $python -B -m pytest -q -rs -p no:cacheprovider --tb=long `
            tests/test_installation_inspector.py tests/test_managed_startup.py `
            tests/test_startup_identity.py tests/test_windows_supervision.py `
            tests/test_native_update.py tests/test_update_desktop_files.py tests/test_local_health.py `
            tests/test_local_activation.py tests/test_activation_state.py
        if ($LASTEXITCODE -ne 0) { throw 'Verification failed. No update was applied.' }
        & (Join-Path $PSScriptRoot 'Build-DesktopLauncher.ps1') -RuntimeRoot $runtime
        Write-Host 'Verification and build only. No task, desktop installation or account was changed.'
        return
    }
    $arguments=@('-B',(Join-Path $PSScriptRoot 'qtrades_update.py'),$Action.ToLowerInvariant(),
                 '--runtime-root',$runtime,'--source',$source)
    if ($Action -eq 'Prepare') {
        $arguments+=@('--releases',(Join-Path $env:LOCALAPPDATA 'RandallAutomationWorks\QTrades\releases'))
    }
    if ($Action -eq 'Activate') {
        $statusPath=Join-Path $runtime 'data\main-update-status.json'
        if ((Get-Item -LiteralPath $statusPath).Length -gt 256000) { throw 'Invalid preparation receipt.' }
        $record=[IO.File]::ReadAllText($statusPath)|ConvertFrom-Json -ErrorAction Stop
        if ($record.phase -ne 'prepared' -or -not $record.prepared_directory -or -not $record.main_commit) {
            throw 'Prepare an approved main release before activating it.'
        }
        $arguments+=@('--release',$record.prepared_directory,'--commit',$record.main_commit)
    }
    if ($Apply) { $arguments+='--apply' }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Q-Trades updater stopped. Preserve the receipt and follow its recovery message.' }
} finally { Pop-Location }
