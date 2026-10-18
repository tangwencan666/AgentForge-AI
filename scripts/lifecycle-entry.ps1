# Shared fixed-project lifecycle entry. No credential values are accessed.
$ErrorActionPreference = 'Stop'
$taskLifecycleRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Invoke-AgentForgeLifecycle([string[]]$TaskArguments) {
    $taskPython = Join-Path $taskLifecycleRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Project Python environment is missing' }
    & $taskPython -B (Join-Path $taskLifecycleRoot 'scripts/lifecycle.py') @TaskArguments
    if ($LASTEXITCODE -ne 0) { throw 'AgentForge lifecycle operation refused or failed; no automatic fallback is allowed' }
}
