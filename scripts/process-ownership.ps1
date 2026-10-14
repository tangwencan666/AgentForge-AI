function Test-AgentForgeProcess($taskProcess, [string]$taskName, [string]$taskRoot) {
    if (-not $taskProcess -or -not $taskProcess.CommandLine -or -not $taskProcess.ExecutablePath) { return $false }
    $taskCommand = $taskProcess.CommandLine.Replace('/', '\')
    $taskExecutable = [System.IO.Path]::GetFullPath($taskProcess.ExecutablePath)
    $taskPython = [System.IO.Path]::GetFullPath((Join-Path $taskRoot '.venv/Scripts/python.exe'))
    $taskVite = [System.IO.Path]::GetFullPath((Join-Path $taskRoot 'frontend/node_modules/vite/bin/vite.js'))
    # Windows venv launcher delegates to the base interpreter; command still starts with this project's venv.
    $taskBackendPrefix = '"' + $taskPython + '" -m uvicorn app.main:create_app'
    $taskBackend = [System.IO.Path]::GetFileName($taskExecutable) -eq 'python.exe' -and ($taskCommand.StartsWith($taskBackendPrefix, [StringComparison]::OrdinalIgnoreCase) -or ($taskExecutable -eq $taskPython -and $taskCommand -like '*-m uvicorn app.main:create_app*'))
    $taskViteArgument = $null
    foreach ($taskArgument in [regex]::Matches($taskCommand, '"([^"]+)"')) {
        if ($taskArgument.Groups[1].Value.EndsWith('\vite\bin\vite.js')) {
            $taskViteArgument = [System.IO.Path]::GetFullPath($taskArgument.Groups[1].Value)
        }
    }
    $taskFrontend = [System.IO.Path]::GetFileName($taskExecutable) -eq 'node.exe' -and ($taskViteArgument -eq $taskVite -or $taskCommand.Contains($taskVite))
    return ($taskName -eq 'backend' -and $taskBackend) -or ($taskName -eq 'frontend' -and $taskFrontend)
}
