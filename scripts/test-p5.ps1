$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPreviousIntegration = $env:AGENTFORGE_RUN_INTEGRATION
$taskPreviousSandbox = $env:AGENTFORGE_RUN_SANDBOX
$taskFaultAttempted = $false
Push-Location $taskRoot
try {
    & (Join-Path $PSScriptRoot 'stop-local.ps1')
    & './.venv/Scripts/python.exe' scripts/migrate.py check
    if ($LASTEXITCODE -ne 0) { throw 'P5 migration consistency check failed' }
    $taskFaultAttempted = $true
    docker compose --profile sandbox-test up -d --no-deps --no-build runner-unavailable
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated P3 regression fault Runner did not start' }
    $env:AGENTFORGE_RUN_INTEGRATION = '1'
    $env:AGENTFORGE_RUN_SANDBOX = '1'
    & './.venv/Scripts/python.exe' -m pytest -c backend/pyproject.toml tests -q --junitxml=work/p5-all.xml
    if ($LASTEXITCODE -ne 0) { throw 'P5 or P3 Python regression failed' }
} finally {
    try {
        if ($taskFaultAttempted) {
            docker compose --profile sandbox-test rm -s -f runner-unavailable
            if ($LASTEXITCODE -ne 0) { throw 'Dedicated fault Runner cleanup was not confirmed' }
        }
    } finally {
        try {
            & (Join-Path $PSScriptRoot 'start-local.ps1')
        } finally {
            $env:AGENTFORGE_RUN_INTEGRATION = $taskPreviousIntegration
            $env:AGENTFORGE_RUN_SANDBOX = $taskPreviousSandbox
            Pop-Location
        }
    }
}
