# Protected or unidentified instances are never stopped by maintenance.
. (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
Invoke-AgentForgeLifecycle -TaskArguments @('stop', '--worker-only')
