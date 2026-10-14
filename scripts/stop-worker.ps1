$ErrorActionPreference='Stop'
$taskRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$taskPidFile=Join-Path $taskRoot 'work/dev-pids.json'
if (Test-Path -LiteralPath $taskPidFile) {
    $taskWorker=Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json | Where-Object { $_.name -eq 'worker' }
    if ($taskWorker) {
        $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWorker.pid)" -ErrorAction SilentlyContinue
        if ($taskProcess) {
            if (-not (Test-AgentForgeProcess $taskProcess 'worker' $taskRoot)) { throw 'Refusing to stop non-project worker' }
            Stop-Process -Id $taskWorker.pid
            Write-Output 'Stopped project P2 worker only'
        }
    }
}
