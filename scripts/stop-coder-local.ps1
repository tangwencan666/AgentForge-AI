# Explicit human maintenance STOP only; the manager requires a real TTY confirmation.
# This does not grant authority to start any replacement or enable model calls.
. (Join-Path $PSScriptRoot 'lifecycle-entry.ps1')
Invoke-AgentForgeLifecycle -TaskArguments @('manual-stop', '--models-only')
