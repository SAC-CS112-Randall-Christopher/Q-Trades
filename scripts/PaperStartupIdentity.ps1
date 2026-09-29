# One exact contract shared by the launcher and read-only installation inspector.
function Test-PaperStartupAction {
    param($Task, [string] $ProjectRoot)
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1 -or -not $actions[0].WorkingDirectory) { return $false }
    $action = $actions[0]
    if ($action.WorkingDirectory.TrimEnd('\') -ine $ProjectRoot.TrimEnd('\')) { return $false }
    $runner = Join-Path $ProjectRoot 'scripts\Run-PaperExperiment.ps1'
    $legacy = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"'
    $hostExe = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
    $hostScript = Join-Path $ProjectRoot 'scripts\service_host.py'
    $hostArgs = '"' + $hostScript + '" --kind paper'
    return (
        ($action.Execute -ieq 'powershell.exe' -and $action.Arguments -ceq $legacy) -or
        ($action.Execute -ieq $hostExe -and $action.Arguments -ceq $hostArgs)
    )
}
