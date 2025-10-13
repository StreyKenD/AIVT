param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$arguments = @('run', 'python', '-m', 'apps.asr_worker.main')

& $serviceManager `
    -ServiceName 'asr_worker' `
    -Command $arguments `
    -Action $Action `
    -Description "Streaming ASR worker (faster-whisper stub)"
