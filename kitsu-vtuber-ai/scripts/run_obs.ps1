param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$arguments = @('run', 'python', '-m', 'apps.obs_controller.main')

& $serviceManager `
    -ServiceName 'obs_controller' `
    -Command $arguments `
    -Action $Action `
    -Description "OBS WebSocket controller"
