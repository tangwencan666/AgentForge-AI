$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'process-ownership.ps1')
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskVenv = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskCases = @(
    @{ process = @{ ExecutablePath = 'D:\python\python.exe'; CommandLine = ('"' + $taskVenv + '" -m uvicorn app.main:create_app --factory') }; name = 'backend'; expected = $true },
    @{ process = @{ ExecutablePath = 'D:\python\python.exe'; CommandLine = 'python -m uvicorn other.main:app' }; name = 'backend'; expected = $false },
    @{ process = @{ ExecutablePath = 'D:\runtime\node.exe'; CommandLine = ('"node" "' + $taskRoot + '\frontend\node_modules\.bin\\..\vite\bin\vite.js" --host 127.0.0.1') }; name = 'frontend'; expected = $true },
    @{ process = @{ ExecutablePath = 'D:\runtime\node.exe'; CommandLine = ('"node" "' + $taskRoot + '-other\frontend\node_modules\vite\bin\vite.js"') }; name = 'frontend'; expected = $false }
)
foreach ($taskCase in $taskCases) {
    if ((Test-AgentForgeProcess ([pscustomobject]$taskCase.process) $taskCase.name $taskRoot) -ne $taskCase.expected) { throw 'Process ownership check failed' }
}
Write-Output 'PASS: 4 process ownership cases; no processes modified'
