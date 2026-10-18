param([switch]$ModelsOnly, [switch]$RestartModels)
. (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
$taskArguments = @('start', '--mode', 'mock')
if ($ModelsOnly) { $taskArguments += '--models-only' }
if ($RestartModels) { $taskArguments += '--restart-models' }
Invoke-AgentForgeLifecycle -TaskArguments $taskArguments
