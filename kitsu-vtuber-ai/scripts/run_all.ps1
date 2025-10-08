param(
    [switch]$UsePoetry
)

# --- Descobrir shell a usar (pwsh > powershell.exe) ---
$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
if ($pwshCmd) {
    $ShellExe = $pwshCmd.Source
} else {
    $ps5Cmd = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($ps5Cmd) {
        $ShellExe = $ps5Cmd.Source
    } else {
        Write-Error "Nenhuma shell encontrada (pwsh nem powershell.exe). Instale PowerShell 7 (pwsh) ou use o PowerShell do Windows."
        exit 1
    }
}

# --- Validação do Poetry quando solicitado ---
if ($UsePoetry) {
    $poetryCmd = Get-Command poetry -ErrorAction SilentlyContinue
    if (-not $poetryCmd) {
        Write-Warning "Você passou -UsePoetry, mas 'poetry' não está no PATH. Vou abortar para evitar janelas quebradas."
        Write-Host "Instale: https://python-poetry.org/docs/  ou rode sem -UsePoetry"
        exit 1
    }
}

# --- Paths e env ---
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Respeita as variáveis de ambiente (definidas via .env / sistema)
$orchHost = if ($env:ORCH_HOST) { $env:ORCH_HOST } else { "127.0.0.1" }
$orchPort = if ($env:ORCH_PORT) { $env:ORCH_PORT } else { "8000" }

function Start-ServiceJob {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Command
    )

    Write-Host "[RUN_ALL] Starting $Name..."

    # Prefixo poetry quando habilitado
    $cmdToRun = if ($UsePoetry) { "poetry run $Command" } else { $Command }

    # Monta argumentos para a shell escolhida
    $argList = @('-NoLogo','-NoExit','-Command', $cmdToRun)

    try {
        Start-Process -FilePath $ShellExe `
                      -ArgumentList $argList `
                      -WindowStyle Minimized `
                      -WorkingDirectory $repoRoot | Out-Null
    } catch {
        Write-Error "[RUN_ALL] Falha ao iniciar '$Name': $($_.Exception.Message)"
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

Write-Host "[RUN_ALL] Pronto. Janelas abertas em segundo plano (minimizadas)."
Write-Host "[RUN_ALL] Orchestrator em: http://$orchHost`:$orchPort/status"
