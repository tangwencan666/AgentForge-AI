# Run only in the user's PowerShell that ALREADY contains the Coder key.
# Start-Process uses native environment inheritance; no key value is accessed here.
$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not (Test-Path Env:\AGENTFORGE_MODEL_CODER_KEY)) { throw 'Coder environment variable is absent in this PowerShell; no process was restarted' }
if (Test-Path Env:\AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN) { throw 'Use a dedicated Coder PowerShell without permit issuer authority; no process was restarted' }
foreach ($taskRole in @('PLANNER', 'RESEARCHER', 'REVIEWER')) {
    if (Test-Path ("Env:\AGENTFORGE_MODEL_" + $taskRole + '_KEY')) { throw 'Use a dedicated PowerShell containing only the intended Coder model credential' }
}
$env:AGENTFORGE_SETTINGS_FILE = Join-Path $taskRoot 'work/p5-live-preflight/.env'
if (-not (Test-Path -LiteralPath $env:AGENTFORGE_SETTINGS_FILE)) { throw 'Prepared service-only settings are missing' }
$env:PYTHONPATH = Join-Path $taskRoot 'backend'
$env:AGENTFORGE_REAL_CALLS_ENABLED = 'false'
$env:AGENTFORGE_SINGLE_USE_PERMITS_ENABLED = 'false'
$env:AGENTFORGE_REAL_WORKER_MODE = 'deny'
$env:AGENTFORGE_REAL_DAILY_BUDGET_USD = '0'
$env:AGENTFORGE_REAL_TEST_BUDGET_USD = '0'
$env:AGENTFORGE_REAL_DAILY_TOKEN_LIMIT = '8256'
$env:AGENTFORGE_REAL_TEST_MAX_CALLS = '1'
$env:AGENTFORGE_ALLOWED_MODEL_HOSTS = 'api.deepseek.com'
$env:AGENTFORGE_MODEL_CREDENTIAL_HOSTS = '{"AGENTFORGE_MODEL_CODER_KEY":["api.deepseek.com"]}'
$taskDefinition = Get-Content -LiteralPath (Join-Path $taskRoot 'config/deepseek-coder-local.json') -Raw | ConvertFrom-Json
$env:AGENTFORGE_MODEL_PRICES = '{"openai_compatible/deepseek-flash":' + ($taskDefinition.price | ConvertTo-Json -Compress -Depth 8) + '}'
$env:AGENTFORGE_REAL_MAX_RETRIES = '0'
$env:AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY = 'true'
$env:AGENTFORGE_EXTERNAL_MODELS_BLOCKED = '1'
$env:LANGCHAIN_TRACING_V2 = 'false'
$env:LANGSMITH_TRACING = 'false'
Push-Location $taskRoot
try {
    & './.venv/Scripts/python.exe' scripts/check-coder-local.py --before-restart
    if ($LASTEXITCODE -ne 0) { throw 'Safety check failed; no process was restarted' }
    . (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
    Invoke-AgentForgeLifecycle -TaskArguments @('start', '--mode', 'coder', '--models-only')
    & './.venv/Scripts/python.exe' scripts/check-coder-local.py
    if ($LASTEXITCODE -ne 0) { throw 'Runtime configuration/presence check failed; keep all live-test switches off' }
} finally { Pop-Location }
