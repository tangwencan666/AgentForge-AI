$ErrorActionPreference='Stop'
$taskRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location $taskRoot
try {
    & (Join-Path $PSScriptRoot 'stop-worker.ps1')
    $env:AGENTFORGE_RUN_INTEGRATION='1'
    & './.venv/Scripts/python.exe' -m pytest -c backend/pyproject.toml tests -q --junitxml=work/p2-all.xml
    if ($LASTEXITCODE -ne 0) { throw 'P2 Python tests failed' }
} finally {
    & (Join-Path $PSScriptRoot 'start-local.ps1')
    Pop-Location
}
