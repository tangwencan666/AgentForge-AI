$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$taskFile = Join-Path $taskRoot 'work/dev-pids.json'
$taskWorker = Get-Content -LiteralPath $taskFile -Raw | ConvertFrom-Json | Where-Object { $_.name -eq 'worker' }
if ($taskWorker) {
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWorker.pid)" -ErrorAction SilentlyContinue
    if ($taskProcess) {
        if (-not (Test-AgentForgeProcess $taskProcess 'worker' $taskRoot)) { throw 'Refusing to restart a non-project worker' }
        Stop-Process -Id $taskWorker.pid
    }
}
& (Join-Path $PSScriptRoot 'start-local.ps1')
