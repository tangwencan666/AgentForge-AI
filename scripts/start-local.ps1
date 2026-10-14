$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$taskEnv = Join-Path $taskRoot '.env'
if (-not (Test-Path -LiteralPath $taskEnv)) { throw 'Run project bootstrap first' }
$taskPorts = @{ BACKEND_PORT = 18100; FRONTEND_PORT = 15173 }
foreach ($taskLine in Get-Content -LiteralPath $taskEnv) {
    if ($taskLine -match '^(BACKEND_PORT|FRONTEND_PORT)=(\d+)$') { $taskPorts[$Matches[1]] = [int]$Matches[2] }
}
$taskWork = Join-Path $taskRoot 'work'
New-Item -ItemType Directory -Path $taskWork -Force | Out-Null
$taskEntries = @(
    @{ name = 'backend'; port = $taskPorts.BACKEND_PORT; file = (Join-Path $taskRoot '.venv/Scripts/python.exe'); args = @('-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port',"$($taskPorts.BACKEND_PORT)",'--no-access-log'); cwd = $taskRoot },
    @{ name = 'frontend'; port = $taskPorts.FRONTEND_PORT; file = 'node'; args = @("`"$(Join-Path $taskRoot 'frontend/node_modules/vite/bin/vite.js')`"",'--host','127.0.0.1'); cwd = (Join-Path $taskRoot 'frontend') }
)
$taskRecords = @()
foreach ($taskEntry in $taskEntries) {
    $taskListener = Get-NetTCPConnection -LocalPort $taskEntry.port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($taskListener) {
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)"
        $taskOwned = Test-AgentForgeProcess $taskProcess $taskEntry.name $taskRoot
        if (-not $taskOwned) { throw "Port $($taskEntry.port) belongs to another project; choose a different port" }
        $taskProcessId = $taskListener.OwningProcess
    } else {
        $taskProcess = Start-Process -FilePath $taskEntry.file -ArgumentList $taskEntry.args -WorkingDirectory $taskEntry.cwd -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskWork "$($taskEntry.name).log") -RedirectStandardError (Join-Path $taskWork "$($taskEntry.name).error.log")
        $taskDeadline = (Get-Date).AddSeconds(10)
        do {
            Start-Sleep -Milliseconds 200
            $taskListener = Get-NetTCPConnection -LocalPort $taskEntry.port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        } until ($taskListener -or (Get-Date) -gt $taskDeadline)
        if (-not $taskListener) { throw "Project $($taskEntry.name) did not start; check project work logs" }
        $taskProcessId = $taskListener.OwningProcess
        $taskActualProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
        if (-not (Test-AgentForgeProcess $taskActualProcess $taskEntry.name $taskRoot)) { throw 'Startup ownership verification failed' }
    }
    $taskRecords += @{ name = $taskEntry.name; pid = $taskProcessId; port = $taskEntry.port }
    Write-Output "$($taskEntry.name): http://127.0.0.1:$($taskEntry.port)"
}
$taskExistingWorker = Get-CimInstance Win32_Process -Filter "CommandLine like '%app.workers.main%'" | Where-Object { Test-AgentForgeProcess $_ 'worker' $taskRoot } | Select-Object -First 1
if (-not $taskExistingWorker) {
    $taskWorkerLauncher = Start-Process -FilePath (Join-Path $taskRoot '.venv/Scripts/python.exe') -ArgumentList @('-m','app.workers.main') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskWork 'worker.log') -RedirectStandardError (Join-Path $taskWork 'worker.error.log')
    Start-Sleep -Seconds 1
    $taskExistingWorker = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskWorkerLauncher.Id)" | Where-Object { Test-AgentForgeProcess $_ 'worker' $taskRoot } | Select-Object -First 1
    if (-not $taskExistingWorker) { $taskExistingWorker = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWorkerLauncher.Id)" | Where-Object { Test-AgentForgeProcess $_ 'worker' $taskRoot } | Select-Object -First 1 }
    if (-not $taskExistingWorker) { throw 'P2 worker did not start; check project dependencies and work logs' }
}
$taskRecords += @{ name = 'worker'; pid = $taskExistingWorker.ProcessId; port = $null }
Write-Output 'worker: independent process (Mock workflows and approved Docker dispatch)'
$taskRecords | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskWork 'dev-pids.json') -Encoding utf8
