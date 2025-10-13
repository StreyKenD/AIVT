param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$arguments = @('run', 'python', '-m', 'apps.tts_worker.main')

& $serviceManager `
    -ServiceName 'tts_worker' `
    -Command $arguments `
    -Action $Action `
    -Description "Text-to-speech worker (Piper / Coqui pipeline)"
