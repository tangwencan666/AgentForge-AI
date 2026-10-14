$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$taskPidFile = Join-Path $taskRoot 'work/dev-pids.json'
if (-not (Test-Path -LiteralPath $taskPidFile)) { Write-Output 'No project process records'; exit 0 }
foreach ($taskRecord in (Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json)) {
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskRecord.pid)" -ErrorAction SilentlyContinue
    if (-not $taskProcess) { continue }
    $taskOwned = Test-AgentForgeProcess $taskProcess $taskRecord.name $taskRoot
    if (-not $taskOwned) { throw "Refusing to stop non-project process $($taskRecord.pid)" }
    Stop-Process -Id $taskRecord.pid
    Write-Output "Stopped project $($taskRecord.name)"
}
