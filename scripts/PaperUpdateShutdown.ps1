# The scheduled host can exit while CREATE_NO_WINDOW descendants remain alive.
# Capture only this runtime's paper processes; never stop by name or PID file alone.
. (Join-Path $PSScriptRoot 'PaperProcessOwnership.ps1')

function Get-RecordedPaperProcess {
    param([string] $RecordPath)
    if (-not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) { return $null }
    $record = Get-Item -LiteralPath $RecordPath
    $saved = (Get-Content -LiteralPath $RecordPath -Raw).Trim()
    if ($saved -notmatch '^[1-9][0-9]{0,8}$') { throw 'Invalid paper PID record; preserving processes.' }
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$saved"
    if (-not $candidate) { return $null }
    $age = ($record.LastWriteTimeUtc - ([DateTime]$candidate.CreationDate).ToUniversalTime()).TotalSeconds
    if ($age -lt 0 -or $age -gt 30) { throw 'Paper PID record has a different lifetime; preserving it.' }
    return $candidate
}

function Test-PaperSupervisorIdentity {
    param($Candidate, [string] $ProjectRoot)
    if (-not $Candidate -or -not $Candidate.CommandLine) { return $false }
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ($Candidate.ExecutablePath -ine $shell) { return $false }
    $runner = Join-Path $ProjectRoot 'scripts\Run-PaperExperiment.ps1'
    $prefix = '(?:"' + [regex]::Escape($shell) + '"|' + [regex]::Escape($shell) + '|powershell\.exe)'
    $file = '(?:"' + [regex]::Escape($runner) + '"|' + [regex]::Escape($runner) + ')'
    return $Candidate.CommandLine.Trim() -match ('^' + $prefix + '\s+-NoProfile\s+-NonInteractive' +
        '(?:\s+-WindowStyle\s+Hidden)?\s+-File\s+' + $file + '$')
}

function Get-PaperUpdateProcessSnapshot {
    param([string] $ProjectRoot)
    $captured = @()
    $supervisor = Get-RecordedPaperProcess (Join-Path $ProjectRoot 'data\supervisor.pid')
    if ($supervisor) {
        if (-not (Test-PaperSupervisorIdentity $supervisor $ProjectRoot)) {
            throw 'Recorded supervisor is not this paper runtime; preserving it.'
        }
        $captured += $supervisor
    }
    $recordPath = Join-Path $ProjectRoot 'data\server.pid'
    $launcher = Get-RecordedPaperProcess $recordPath
    if ($launcher) {
        $recordedAt = (Get-Item -LiteralPath $recordPath).LastWriteTimeUtc
        $python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
        if (-not (Test-PaperLauncherIdentity $launcher $python $recordedAt)) {
            throw 'Recorded launcher is not this paper runtime; preserving it.'
        }
        # Stop the verified supervisor first so it cannot relaunch the worker.
        # Only the immediate, verified base-interpreter child belongs in the list.
        $captured += @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($launcher.ProcessId)" |
            Where-Object { Test-PaperWorkerIdentity $_ $launcher })
        $captured += $launcher
    }
    return $captured
}

function Stop-VerifiedPaperUpdateProcesses {
    param($Snapshot)
    foreach ($saved in @($Snapshot)) {
        $process = Get-Process -Id $saved.ProcessId -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        try {
            # Pin the process handle before comparing identity, preventing PID reuse
            # between the CIM check and Stop-Process's use of this process object.
            $null = $process.Handle
            $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.ProcessId)"
            if (-not $current) { continue }
            if ($current.ExecutablePath -ine $saved.ExecutablePath -or
                $current.CommandLine -cne $saved.CommandLine -or
                ([DateTime]$current.CreationDate) -ne ([DateTime]$saved.CreationDate)) {
                throw 'Paper process identity changed during shutdown; preserving it.'
            }
            Stop-Process -InputObject $process -ErrorAction Stop
            Write-Host "Stopped verified paper process $($saved.ProcessId)."
        } finally { $process.Dispose() }
    }
}
