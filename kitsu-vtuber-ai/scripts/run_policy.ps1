param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$serviceManager = Join-Path $PSScriptRoot 'service_manager.ps1'
$listenHost = if ($env:POLICY_HOST) { $env:POLICY_HOST } else { '0.0.0.0' }
$listenPort = if ($env:POLICY_PORT) { $env:POLICY_PORT } else { '8081' }

$arguments = @('run', 'uvicorn', 'apps.policy_worker.main:app', '--host', $listenHost, '--port', $listenPort)
if ($env:UVICORN_RELOAD -eq '1') {
    $arguments += '--reload'
}

& $serviceManager `
    -ServiceName 'policy_worker' `
    -Command $arguments `
    -Action $Action `
    -Description "Policy worker (Ollama Mixtral streaming API)"
