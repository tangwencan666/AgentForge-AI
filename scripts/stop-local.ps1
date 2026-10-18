param([switch]$ModelsOnly)
. (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
$taskArguments = @('stop')
if ($ModelsOnly) { $taskArguments += '--models-only' }
Invoke-AgentForgeLifecycle -TaskArguments $taskArguments
