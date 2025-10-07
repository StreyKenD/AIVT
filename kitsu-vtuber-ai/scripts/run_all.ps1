param(
    [switch]$UsePoetry
)

function Start-ServiceJob {
    param(
        [string]$Name,
        [string]$Command
    )

    Write-Host "[RUN_ALL] Starting $Name..."
    if ($UsePoetry) {
        Start-Process pwsh -ArgumentList "-NoLogo", "-NoExit", "-Command", "poetry run $Command" -WindowStyle Minimized
    }
    else {
        Start-Process pwsh -ArgumentList "-NoLogo", "-NoExit", "-Command", "$Command" -WindowStyle Minimized
    }
}

$services = @(
    @{ Name = "orchestrator"; Command = "uvicorn apps.orchestrator.main:app --reload" },
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
