# Match the existing project task; never repoint it as part of an update.
function Test-PaperStartupAction {
    param($Task, [string] $ProjectRoot)
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) { return $false }
    $action = $actions[0]
    if ($action.WorkingDirectory.TrimEnd('\') -ine $ProjectRoot.TrimEnd('\')) { return $false }
    $runner = Join-Path $ProjectRoot 'scripts\Run-PaperExperiment.ps1'
    $legacy = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"'
    $hostExe = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
    $hostArgs = '"' + (Join-Path $ProjectRoot 'scripts\service_host.py') + '" --kind paper'
    return ($action.Execute -ieq 'powershell.exe' -and $action.Arguments -ceq $legacy) -or
        ($action.Execute -ieq $hostExe -and $action.Arguments -ceq $hostArgs)
}
