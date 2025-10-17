param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$arguments = @('run', 'python', '-m', 'apps.pipeline_runner.main')

& $serviceManager `
    -ServiceName 'pipeline' `
    -Command $arguments `
    -Action $Action `
    -Description "Runs orchestrator + workers under a single supervisor loop"

