. (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
Invoke-AgentForgeLifecycle -TaskArguments @('maintenance-run', '--phase', 'p2')
