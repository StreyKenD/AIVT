param(
    [switch]$UsePoetry
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$orchHost = if ($env:ORCH_HOST) { $env:ORCH_HOST } else { "127.0.0.1" }
$orchPort = if ($env:ORCH_PORT) { $env:ORCH_PORT } else { "8000" }

function Start-ServiceJob {
    param(
        [string]$Name,
        [string]$Command
    )

    Write-Host "[RUN_ALL] Starting $Name..."
    $arguments = if ($UsePoetry) { "poetry run $Command" } else { $Command }

    Start-Process pwsh -ArgumentList "-NoLogo", "-NoExit", "-Command", $arguments -WindowStyle Minimized -WorkingDirectory $repoRoot
}

$services = @(
    @{ Name = "orchestrator"; Command = ("uvicorn apps.orchestrator.main:app --reload --host {0} --port {1}" -f $orchHost, $orchPort) },
    @{ Name = "control_panel"; Command = "uvicorn apps.control_panel_backend.main:app --reload" },
    @{ Name = "asr_worker"; Command = "python -m apps.asr_worker.main" },
    @{ Name = "policy_worker"; Command = "python -m apps.policy_worker.main" },
    @{ Name = "tts_worker"; Command = "python -m apps.tts_worker.main" },
    @{ Name = "avatar_controller"; Command = "python -m apps.avatar_controller.main" },
    @{ Name = "obs_controller"; Command = "python -m apps.obs_controller.main" },
    @{ Name = "twitch_ingest"; Command = "python -m apps.twitch_ingest.main" }
)

foreach ($svc in $services) {
    Start-ServiceJob -Name $svc.Name -Command $svc.Command
}
