param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$host = if ($env:ORCH_HOST) { $env:ORCH_HOST } else { '127.0.0.1' }
$port = if ($env:ORCH_PORT) { $env:ORCH_PORT } else { '8000' }

$arguments = @('run', 'uvicorn', 'apps.orchestrator.main:app', '--host', $host, '--port', $port)
if ($env:UVICORN_RELOAD -eq '1') {
    $arguments += '--reload'
}

& $serviceManager `
    -ServiceName 'orchestrator' `
    -Command $arguments `
    -Action $Action `
    -Description "FastAPI orchestrator (serves /status and /stream)"
