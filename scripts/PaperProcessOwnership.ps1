# No side effects when dot-sourced. PID files alone are not proof of ownership.
function Test-PaperLauncherIdentity {
    param($Candidate, [string] $PythonPath, [DateTime] $RecordedAt, [string] $RuntimeRoot)
    if ($null -eq $Candidate -or $Candidate.ExecutablePath -ne $PythonPath) { return $false }
    $expected = '"' + $PythonPath + '" -m trading serve --experiment'
    if ($RuntimeRoot) { $expected += ' --runtime-root "' + $RuntimeRoot + '"' }
    if ($Candidate.CommandLine.Trim() -ne $expected) { return $false }
    $age = ($RecordedAt.ToUniversalTime() - ([DateTime]$Candidate.CreationDate).ToUniversalTime()).TotalSeconds
    return $age -ge 0 -and $age -le 30
}

function Get-ExistingPaperServer {
    param([string] $PythonPath, [string] $PidPath, $Listeners, [string] $RuntimeRoot)
    if ($Listeners.Count -ne 1 -or $Listeners[0].LocalAddress -ne '127.0.0.1') {
        throw 'Port 8780 has an unexpected listener; preserving it.'
    }
    $record = Get-Item -LiteralPath $PidPath -ErrorAction Stop
    $launcherId = [int](Get-Content -LiteralPath $PidPath -Raw -ErrorAction Stop).Trim()
    $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$launcherId"
    if (-not (Test-PaperLauncherIdentity $launcher $PythonPath $record.LastWriteTimeUtc $RuntimeRoot)) {
        throw 'Existing paper launcher identity is not verified; preserving it.'
    }
    if ($Listeners[0].OwningProcess -ne $launcherId) {
        $worker = Get-CimInstance Win32_Process -Filter "ProcessId=$($Listeners[0].OwningProcess)"
        if (-not (Test-PaperWorkerIdentity $worker $launcher $RuntimeRoot)) {
            throw 'Existing paper listener does not belong to the verified launcher.'
        }
    }
    return Get-Process -Id $launcherId -ErrorAction Stop
}

function Test-PaperWorkerIdentity {
    param($Worker, $Launcher, [string] $RuntimeRoot)
    if ($null -eq $Worker -or $Worker.ParentProcessId -ne $Launcher.ProcessId -or $Worker.Name -ne 'python.exe' -or -not $Worker.ExecutablePath) { return $false }
    # The venv launcher creates a base-interpreter child with a different executable prefix.
    $expected = '"' + $Worker.ExecutablePath + '" -m trading serve --experiment'
    if ($RuntimeRoot) { $expected += ' --runtime-root "' + $RuntimeRoot + '"' }
    $age = (([DateTime]$Worker.CreationDate).ToUniversalTime() - ([DateTime]$Launcher.CreationDate).ToUniversalTime()).TotalSeconds
    return $Worker.CommandLine.Trim() -eq $expected -and $age -ge 0 -and $age -le 30
}
