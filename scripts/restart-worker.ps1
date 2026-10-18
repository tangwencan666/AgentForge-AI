# A restart is one locked operation; no standalone stop/start gap.
. (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
Invoke-AgentForgeLifecycle -TaskArguments @('restart-worker')
