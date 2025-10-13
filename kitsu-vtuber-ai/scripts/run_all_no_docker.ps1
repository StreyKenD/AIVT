param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start"
)

$services = @(
    'run_orchestrator.ps1',
    'run_asr.ps1',
    'run_policy.ps1',
    'run_tts.ps1',
    'run_twitch.ps1',
    'run_obs.ps1',
    'run_vts.ps1'
)

foreach ($script in $services) {
    $path = Join-Path $PSScriptRoot $script
    if (-not (Test-Path $path)) {
        Write-Warning "Script $script not found."
        continue
    }

    Write-Host "[kitsu] Executing $script ($Action)..." -ForegroundColor Magenta
    & $path -Action $Action
}

if ($Action -eq 'start') {
    Write-Host "[kitsu] All services requested. Use '-Action status' to inspect running processes." -ForegroundColor Green
}
