# Dot-sourcing has no OS/task side effects.
function Get-ResearchProcessHandle {
    param($Candidate, [DateTime] $ExpectedStart, [int] $ExpectedParent, [string[]] $AllowedPaths)
    if ($null -eq $Candidate) { return $null }
    if ($Candidate.ParentProcessId -ne $ExpectedParent -or $Candidate.ExecutablePath -notin $AllowedPaths) {
        throw 'Research process path or parent differs; preserving uncertain ownership.'
    }
    $process = Get-Process -Id $Candidate.ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        # Opening Handle pins this process lifetime. Kill/HasExited use the cached
        # handle in Windows PowerShell 5.1's .NET Process, never a later PID lookup.
        $null = $process.Handle
        $started = $process.StartTime.ToUniversalTime()
        # CIM creation timestamps have microsecond precision; native starts have
        # 100ns precision. Never compare large tick values through a double.
        if ([Math]::Abs(($started - $ExpectedStart.ToUniversalTime()).Ticks) -gt 9 -or
            [Math]::Abs(($started - ([DateTime]$Candidate.CreationDate).ToUniversalTime()).Ticks) -gt 9) {
            throw 'Research process lifetime changed; preserving uncertain ownership.'
        }
        return $process
    } catch {
        $process.Dispose()
        throw
    }
}

function Stop-ResearchProcessHandle {
    param($Process)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            $Process.Kill()
            if (-not $Process.WaitForExit(5000)) { throw 'Owned research process has not exited.' }
        }
    } catch {
        # Exit can race Kill, but the pinned handle can never target a replacement.
        if (-not $Process.HasExited) { throw }
    }
}

function Enter-ResearchMaintenance {
    param([string] $DataDirectory)
    $held = New-Object 'System.Collections.Generic.List[System.IO.FileStream]'
    try {
        if (-not (Test-Path -LiteralPath $DataDirectory -PathType Container)) {
            New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
        }
        foreach ($name in @('research-qualification-queue.lock', 'research-inference.lock')) {
            $handle = [IO.File]::Open((Join-Path $DataDirectory $name), [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
            try {
                if ($handle.Length -eq 0) { $handle.WriteByte(48); $handle.Flush() }
                # Same byte as CollectorLock / msvcrt.LK_NBLCK. Do not truncate,
                # replace or delete the file; admission shares this OS boundary.
                $handle.Lock(0, 1)
                $held.Add($handle)
            } catch { $handle.Dispose(); throw 'Research work owns admission; preserve it before runtime maintenance.' }
        }
        return ,$held
    } catch {
        foreach ($handle in $held) { $handle.Dispose() }
        throw
    }
}
