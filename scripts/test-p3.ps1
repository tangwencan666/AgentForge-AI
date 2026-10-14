$ErrorActionPreference='Stop'
$taskRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location $taskRoot
$taskFaultAttempted=$false
$taskPreviousIntegration=$env:AGENTFORGE_RUN_INTEGRATION
$taskPreviousSandbox=$env:AGENTFORGE_RUN_SANDBOX
try {
    & (Join-Path $PSScriptRoot 'stop-worker.ps1')
    # Compose can create the dedicated container before startup returns an error.
    $taskFaultAttempted=$true
    docker compose --profile sandbox-test up -d --no-deps --no-build runner-unavailable
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated unavailable-daemon test Runner did not start' }
    $env:AGENTFORGE_RUN_INTEGRATION='1'
    $env:AGENTFORGE_RUN_SANDBOX='1'
    & './.venv/Scripts/python.exe' -m pytest -c backend/pyproject.toml tests -q --junitxml=work/p3-all.xml
    if ($LASTEXITCODE -ne 0) { throw 'P3 Python or real sandbox tests failed' }
} finally {
    try {
        try {
            if ($taskFaultAttempted) {
                # Service-scoped cleanup; never remove another Compose service.
                docker compose --profile sandbox-test rm -s -f runner-unavailable
                if ($LASTEXITCODE -ne 0) { throw 'Dedicated test Runner cleanup was not confirmed' }
            }
        } finally {
            & (Join-Path $PSScriptRoot 'start-local.ps1')
        }
    } finally {
        try {
            if ($null -eq $taskPreviousIntegration) {
                Remove-Item -LiteralPath 'Env:AGENTFORGE_RUN_INTEGRATION' -ErrorAction SilentlyContinue
            } else {
                $env:AGENTFORGE_RUN_INTEGRATION=$taskPreviousIntegration
            }
            if ($null -eq $taskPreviousSandbox) {
                Remove-Item -LiteralPath 'Env:AGENTFORGE_RUN_SANDBOX' -ErrorAction SilentlyContinue
            } else {
                $env:AGENTFORGE_RUN_SANDBOX=$taskPreviousSandbox
            }
        } finally {
            Pop-Location
        }
    }
}
