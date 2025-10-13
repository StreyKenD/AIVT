param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$arguments = @('run', 'python', '-m', 'apps.avatar_controller.main')

& $serviceManager `
    -ServiceName 'avatar_controller' `
    -Command $arguments `
    -Action $Action `
    -Description "VTube Studio controller"
