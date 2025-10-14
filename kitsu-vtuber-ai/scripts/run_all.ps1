param(
    [switch]$UsePoetry
)

# --- Determine which shell to use (pwsh > powershell.exe) ---
$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
if ($pwshCmd) {
    $ShellExe = $pwshCmd.Source
} else {
    $ps5Cmd = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($ps5Cmd) {
        $ShellExe = $ps5Cmd.Source
    } else {
        Write-Error "No shell found (neither pwsh nor powershell.exe). Install PowerShell 7 (pwsh) or use Windows PowerShell."
        exit 1
    }
}

# --- Validate Poetry when requested ---
if ($UsePoetry) {
    $poetryCmd = Get-Command poetry -ErrorAction SilentlyContinue
    if (-not $poetryCmd) {
        Write-Warning "You passed -UsePoetry, but 'poetry' is not on PATH. Aborting to avoid broken windows."
        Write-Host "Install: https://python-poetry.org/docs/  or run without -UsePoetry"
        exit 1
    }
}

# --- Paths and environment ---
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Respect environment variables (defined via .env / system)
$orchHost = if ($env:ORCH_HOST) { $env:ORCH_HOST } else { "127.0.0.1" }
$orchPort = if ($env:ORCH_PORT) { $env:ORCH_PORT } else { "8000" }

function Start-ServiceJob {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Command
    )

    Write-Host "[RUN_ALL] Starting $Name..."

    # Prefix with poetry when enabled
    $cmdToRun = if ($UsePoetry) { "poetry run $Command" } else { $Command }

    # Build arguments for the selected shell
    $argList = @('-NoLogo','-NoExit','-Command', $cmdToRun)

    try {
        Start-Process -FilePath $ShellExe `
                      -ArgumentList $argList `
                      -WindowStyle Minimized `
                      -WorkingDirectory $repoRoot | Out-Null
    } catch {
        Write-Error "[RUN_ALL] Failed to start '$Name': $($_.Exception.Message)"
    }
}

$services = @(
    @{ Name = "orchestrator";      Command = ("uvicorn apps.orchestrator.main:app --reload --host {0} --port {1}" -f $orchHost, $orchPort) },
    @{ Name = "control_panel";     Command = "uvicorn apps.control_panel_backend.main:app --reload" },
    @{ Name = "asr_worker";        Command = "python -m apps.asr_worker.main" },
    @{ Name = "policy_worker";     Command = "python -m apps.policy_worker.main" },
    @{ Name = "tts_worker";        Command = "python -m apps.tts_worker.main" },
    @{ Name = "avatar_controller"; Command = "python -m apps.avatar_controller.main" },
    @{ Name = "obs_controller";    Command = "python -m apps.obs_controller.main" },
    @{ Name = "twitch_ingest";     Command = "python -m apps.twitch_ingest.main" }
)

foreach ($svc in $services) {
    Start-ServiceJob -Name $svc.Name -Command $svc.Command
}

Write-Host "[RUN_ALL] Done. Windows opened in the background (minimized)."
Write-Host "[RUN_ALL] Orchestrator at: http://$orchHost`:$orchPort/status"
