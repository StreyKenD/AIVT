param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$arguments = @('run', 'python', '-m', 'apps.twitch_ingest.main')

& $serviceManager `
    -ServiceName 'twitch_ingest' `
    -Command $arguments `
    -Action $Action `
    -Description "Twitch chat ingest (OAuth + commands)"
