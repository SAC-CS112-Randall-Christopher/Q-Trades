# Native operations for qtrades_update.py. No unattended or network-triggered activation.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('inspect','prepare_desktop','stop','configure_target','configure_previous','start','install_desktop','restore_desktop')]
    [string] $Action,
    [Parameter(Mandatory=$true)][string] $Request
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')
. (Join-Path $PSScriptRoot 'PaperProcessOwnership.ps1')
$taskName = 'TradingResearch-Paper-20260927'
function Read-BoundedJson([string] $Path) {
    if ((Get-Item -LiteralPath $Path).Length -gt 256000) { throw 'Oversize local update record.' }
    return ([IO.File]::ReadAllText($Path) | ConvertFrom-Json -ErrorAction Stop)
}
$plan = Read-BoundedJson $Request
$runtime = (Resolve-Path -LiteralPath $plan.runtime_root).Path
foreach ($path in @($runtime, $plan.old_root, $plan.target_root)) {
    if ($path -and ($path.Contains('"') -or $path.Contains("`n") -or $path.Contains("`r"))) {
        throw 'Unsupported local path; no process command was dispatched.'
    }
}
function File-Hash([string] $Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $null
}
function Task-Signature {
    # All task settings/principal/triggers retained. Only Action and Enabled may change.
    [xml] $xml = Export-ScheduledTask -TaskName $taskName -TaskPath '\'
    foreach ($node in @($xml.SelectNodes("//*[local-name()='Actions'] | /*[local-name()='Task']/*[local-name()='Settings']/*[local-name()='Enabled']"))) {
        [void]$node.ParentNode.RemoveChild($node)
    }
    return $xml.OuterXml
}
function Get-OwnedTask {
    $task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
    if (@($task.Actions).Count -ne 1) { throw 'Unexpected number of task actions.' }
    $code = $task.Actions[0].WorkingDirectory.TrimEnd('\')
    $dataArgument = if ($code -ine $runtime.TrimEnd('\')) { $runtime } else { '' }
    if (-not (Test-PaperStartupAction $task $code $dataArgument)) { throw 'Task identity changed.' }
    if ($plan.old_root -and $code -ine $plan.old_root -and $code -ine $plan.target_root) {
        throw 'Task points outside this update; preserving it.'
    }
    if ($plan.previous -and (Task-Signature) -cne $plan.previous.signature) {
        throw 'Task settings, principal or triggers changed; preserving them.'
    }
    return $task
}
function Join-NativeCommand([string[]] $Tokens) {
    return (($Tokens | ForEach-Object {
        if ($_ -match '\s' -or $_ -eq '') { '"' + $_ + '"' } else { $_ }
    }) -join ' ')
}
function Test-HostCommand($Process, [string] $Code, [string] $DataArgument) {
    if ($Process.Name -ine 'pythonw.exe') { return $false }
    $tail = '"' + (Join-Path $Code 'scripts\service_host.py') + '" --kind paper'
    $tokens = @($Process.ExecutablePath, (Join-Path $Code 'scripts\service_host.py'), '--kind', 'paper')
    if ($DataArgument) { $tail += ' --runtime-root "' + $DataArgument + '"'; $tokens += @('--runtime-root', $DataArgument) }
    $line = $Process.CommandLine.Trim()
    return $line -ceq ('"'+$Process.ExecutablePath+'" '+$tail) -or
        $line -ceq ($Process.ExecutablePath+' '+$tail) -or $line -ceq (Join-NativeCommand $tokens)
}
function Get-Inspection([switch] $Processes) {
    $task = Get-OwnedTask
    $code = $task.Actions[0].WorkingDirectory.TrimEnd('\')
    $dataArgument = if ($code -ine $runtime.TrimEnd('\')) { $runtime } else { '' }
    $listeners = @(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue)
    $identities = [Collections.Generic.List[object]]::new()
    $owned = $false
    if ($listeners.Count) {
        $launcher = Get-ExistingPaperServer (Join-Path $code '.venv\Scripts\python.exe') `
            (Join-Path $runtime 'data\server.pid') $listeners $dataArgument
        try { $launcherId = $launcher.Id } finally { $launcher.Dispose() }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$launcherId"
        $identities.Add($process)
        if ($listeners[0].OwningProcess -ne $launcherId) {
            $identities.Add((Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"))
        }
        $owned = $true
    }
    if ($Processes) {
        $recordPath = Join-Path $runtime 'data\service-host-paper.json'
        if (Test-Path -LiteralPath $recordPath) {
            $record = Read-BoundedJson $recordPath
            $hostProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$record.host_pid)"
            if ($hostProcess) {
                $age = (([DateTime]$record.started_at).ToUniversalTime() - ([DateTime]$hostProcess.CreationDate).ToUniversalTime()).TotalSeconds
                if (-not (Test-HostCommand $hostProcess $code $dataArgument) -or $age -lt 0 -or $age -gt 30) { throw 'Host process identity changed.' }
                $identities.Add($hostProcess)
            }
            if ($record.supervisor_pid) {
                $supervisor = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$record.supervisor_pid)"
                if ($supervisor) {
                    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
                    $tokens = @($shell,'-NoProfile','-NonInteractive','-File',(Join-Path $code 'scripts\Run-PaperExperiment.ps1'))
                    if ($dataArgument) { $tokens += @('-RuntimeRoot',$dataArgument) }
                    $age = (([DateTime]$supervisor.CreationDate).ToUniversalTime() - ([DateTime]$record.started_at).ToUniversalTime()).TotalSeconds
                    if ($supervisor.ParentProcessId -ne $record.host_pid -or $supervisor.ExecutablePath -ine $shell -or
                        $supervisor.CommandLine.Trim() -cne (Join-NativeCommand $tokens) -or $age -lt 0 -or $age -gt 30) {
                        throw 'Supervisor process identity changed.'
                    }
                    $identities.Add($supervisor)
                }
            }
        } elseif ($task.State -eq 'Running') { throw 'Running task has no verifiable host receipt.' }
    }
    $result = [ordered]@{
        code_root=$code;owned=$owned;enabled=[bool]$task.Settings.Enabled
        signature=(Task-Signature);action=[ordered]@{
            Execute=$task.Actions[0].Execute;Arguments=$task.Actions[0].Arguments;WorkingDirectory=$code
        }
    }
    if ($Processes) { $result['processes'] = @($identities.ToArray()) }
    return $result
}
function Stop-VerifiedInstallation {
    $inspection = Get-Inspection -Processes
    # Open and retain handles before stopping the task: reused numeric PIDs are never killed.
    $handles = [Collections.Generic.List[object]]::new()
    try {
        foreach ($identity in $inspection.processes) {
            $process = Get-Process -Id $identity.ProcessId -ErrorAction SilentlyContinue
            if (-not $process) { continue }
            [void]$process.Handle
            # WMI timestamps can truncate sub-millisecond ticks. Hold the process handle
            # throughout, and reject a creation-time change of one millisecond or more.
            $delta = ($process.StartTime.ToUniversalTime() - ([DateTime]$identity.CreationDate).ToUniversalTime()).TotalMilliseconds
            if ([math]::Abs($delta) -ge 1) {
                $process.Dispose(); throw 'A process ID was reused; no process was stopped.'
            }
            $handles.Add($process)
        }
        Disable-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
        Stop-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
        for ($i=$handles.Count-1; $i -ge 0; $i--) {
            $process = $handles[$i]
            if (-not $process.HasExited) {
                $process.Kill()
                if (-not $process.WaitForExit(10000)) { throw 'An owned process did not exit.' }
            }
        }
        if (@(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue).Count) {
            throw 'A listener remains; no replacement was started.'
        }
        $mutex = New-Object Threading.Mutex($false,'Local\TradingResearchPaper20260927')
        $held=$false
        try {
            try { $held=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held=$true }
            if (-not $held) { throw 'Another paper supervisor still owns the service.' }
        } finally { if ($held) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
    } finally { foreach ($process in $handles) { $process.Dispose() } }
}
function Require-Stopped {
    $task = Get-OwnedTask
    if ($task.Settings.Enabled -or $task.State -eq 'Running' -or
        @(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue).Count) {
        throw 'Task or listener is active; configuration was not changed.'
    }
}
$result = @{ok=$true}
switch ($Action) {
    'inspect' { $result = Get-Inspection }
    'prepare_desktop' {
        $build = & (Join-Path $plan.target_root 'scripts\Build-DesktopLauncher.ps1') -RuntimeRoot $runtime | ConvertFrom-Json
        $desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Trading Research.exe'
        $oldHash = File-Hash $desktop
        if ($oldHash -and $oldHash -ne (File-Hash (Join-Path $plan.old_root 'data\desktop-launcher-build\Trading Research.exe'))) {
            throw 'Existing desktop file is not the recorded launcher; preserving it.'
        }
        $backup = Join-Path $runtime ('data\update-receipts\'+$plan.id+'-desktop-before.exe')
        if ($oldHash) {
            Copy-Item -LiteralPath $desktop -Destination $backup -ErrorAction Stop
            if ((File-Hash $backup) -ne $oldHash) { throw 'Desktop backup did not verify.' }
        }
        $result = @{path=$desktop;before_hash=$oldHash;backup=$backup;new_file=$build.Executable;new_hash=(File-Hash $build.Executable)}
    }
    'stop' { Stop-VerifiedInstallation }
    'configure_target' {
        Require-Stopped
        $code = $plan.target_root
        $arguments = '"'+(Join-Path $code 'scripts\service_host.py')+'" --kind paper --runtime-root "'+$runtime+'"'
        $actionObject = New-ScheduledTaskAction -Execute (Join-Path $code '.venv\Scripts\pythonw.exe') -Argument $arguments -WorkingDirectory $code
        Set-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $actionObject | Out-Null
        [void](Get-OwnedTask)
    }
    'configure_previous' {
        Require-Stopped
        $old = $plan.previous.action
        $actionObject = New-ScheduledTaskAction -Execute $old.Execute -Argument $old.Arguments -WorkingDirectory $old.WorkingDirectory
        Set-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $actionObject | Out-Null
        [void](Get-OwnedTask)
    }
    'start' {
        $task = Get-OwnedTask
        if ($task.Actions[0].WorkingDirectory.TrimEnd('\') -ine $plan.launch.code_root) { throw 'Wrong launch target.' }
        if (@(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue).Count) { throw 'Listener already active; no duplicate started.' }
        Enable-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
        Start-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
    }
    'install_desktop' {
        $d = $plan.desktop
        if ((File-Hash $d.path) -ne $d.before_hash -or (File-Hash $d.new_file) -ne $d.new_hash) { throw 'Desktop file changed; preserving it.' }
        $temporary = $d.path+'.'+$plan.id+'.tmp'
        Copy-Item -LiteralPath $d.new_file -Destination $temporary -ErrorAction Stop
        if ((File-Hash $temporary) -ne $d.new_hash) { throw 'New desktop copy did not verify.' }
        Move-Item -LiteralPath $temporary -Destination $d.path -Force -ErrorAction Stop
        if ((File-Hash $d.path) -ne $d.new_hash) { throw 'Installed desktop hash mismatch.' }
    }
    'restore_desktop' {
        $d = $plan.desktop
        $current = File-Hash $d.path
        if ($current -eq $d.before_hash) { break }
        if ($current -ne $d.new_hash) { throw 'Desktop changed since update; preserving it.' }
        if ($d.before_hash) {
            if ((File-Hash $d.backup) -ne $d.before_hash) { throw 'Desktop backup changed.' }
            Copy-Item -LiteralPath $d.backup -Destination $d.path -Force -ErrorAction Stop
        } else { Remove-Item -LiteralPath $d.path -ErrorAction Stop }
        if ((File-Hash $d.path) -ne $d.before_hash) { throw 'Desktop restoration did not verify.' }
    }
}
$result | ConvertTo-Json -Depth 8 -Compress
