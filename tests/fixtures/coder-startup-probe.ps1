# Explicit fake variable used only for the native inheritance regression.
param([switch]$PolicyOnly, [switch]$IssuerPresent)
$ErrorActionPreference = 'Stop'
if (-not $PolicyOnly) { throw 'Native inheritance probe is disabled: offline fixtures cannot replace the main Coder services' }
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$env:AGENTFORGE_MODEL_CODER_KEY = 'explicit-native-inheritance-test-fake-only'
if ($PolicyOnly) {
    # Execute only the real launcher's policy preamble. No service/DB/config operations.
    $taskLauncher = Join-Path $taskRoot 'scripts/start-coder-local.ps1'
    $taskSource = Get-Content -LiteralPath $taskLauncher -Raw
    $taskStop = $taskSource.IndexOf('Push-Location $taskRoot', [StringComparison]::Ordinal)
    if ($taskStop -lt 0) { throw 'Reviewed policy boundary missing' }
    function Test-Path {
        param([string]$Path, [string]$LiteralPath)
        if ($LiteralPath) {
            if ($LiteralPath -ne (Join-Path $taskRoot 'work/p5-live-preflight/.env')) { throw 'Unexpected file probe' }
            return $true # Explicit file-existence double; no settings or credentials are read.
        }
        Microsoft.PowerShell.Management\Test-Path $Path
    }
    $env:AGENTFORGE_SINGLE_USE_PERMITS_ENABLED = 'true'
    $env:AGENTFORGE_REAL_WORKER_MODE = 'permit_only'
    $env:AGENTFORGE_REAL_CALLS_ENABLED = 'true'
    $env:AGENTFORGE_REAL_DAILY_BUDGET_USD = '.005'
    $env:AGENTFORGE_REAL_TEST_BUDGET_USD = '.005'
    if ($IssuerPresent) { $env:AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN = 'explicit-fake-issuer-never-used' }
    $taskPolicy = [scriptblock]::Create("param([string]`$PSScriptRoot)`n" + $taskSource.Substring(0, $taskStop))
    try {
        & $taskPolicy (Split-Path -Parent $taskLauncher)
        if ($IssuerPresent) { throw 'Unexpected issuer inheritance' }
    } catch {
        if ($IssuerPresent -and $_.Exception.Message -eq 'Use a dedicated Coder PowerShell without permit issuer authority; no process was restarted') {
            @{ issuer_rejected = $true; service_start_attempts = 0; external_model_calls = 0 } | ConvertTo-Json -Compress
            exit 0
        }
        throw
    }
    if ($env:AGENTFORGE_SINGLE_USE_PERMITS_ENABLED -ne 'false' -or $env:AGENTFORGE_REAL_WORKER_MODE -ne 'deny' -or
        $env:AGENTFORGE_REAL_CALLS_ENABLED -ne 'false' -or $env:AGENTFORGE_REAL_DAILY_BUDGET_USD -ne '0' -or
        $env:AGENTFORGE_REAL_TEST_BUDGET_USD -ne '0' -or $env:AGENTFORGE_EXTERNAL_MODELS_BLOCKED -ne '1' -or
        $env:AGENTFORGE_REAL_MAX_RETRIES -ne '0') { throw 'Unsafe policy survived startup preamble' }
    @{ policy_closed = $true; coder_name_present = (Test-Path Env:\AGENTFORGE_MODEL_CODER_KEY);
       service_start_attempts = 0; external_model_calls = 0 } | ConvertTo-Json -Compress
    exit 0
}
