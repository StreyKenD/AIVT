param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start",
    [string]$LogRoot
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

$originalLogRoot = $env:KITSU_LOG_ROOT
$resolvedLogRoot = $null

try {
    if ($Action -eq 'start') {
        $candidate = if ($LogRoot) { $LogRoot } else { Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'logs' }
        if (-not (Test-Path $candidate)) {
            New-Item -ItemType Directory -Path $candidate -Force | Out-Null
        }
        $resolvedLogRoot = (Resolve-Path -Path $candidate).Path
        $env:KITSU_LOG_ROOT = $resolvedLogRoot
        Write-Host "[kitsu] Logs will be written to $resolvedLogRoot" -ForegroundColor DarkGray
    }

    $failures = @()

    foreach ($script in $services) {
        $path = Join-Path $PSScriptRoot $script
        if (-not (Test-Path $path)) {
            $failures += "Script $script not found."
            Write-Error "[kitsu] Script $script not found."
            continue
        }

        Write-Host "[kitsu] Executing $script ($Action)..." -ForegroundColor Magenta
        try {
            & $path -Action $Action
            if (-not $?) {
                $failures += "Script $script reported an error while executing '$Action'."
                continue
            }

            if ($Action -eq 'start') {
                & $path -Action 'status' | Out-Null
            }
        } catch {
            $failures += "Script $script threw an exception: $($_.Exception.Message)"
            Write-Error $_
        }
    }

    if ($failures.Count -gt 0) {
        Write-Error "[kitsu] One or more services failed:"
        foreach ($failure in $failures) {
            Write-Error " - $failure"
        }
        exit 1
    }

    switch ($Action) {
        'start' {
            Write-Host "[kitsu] All services started successfully. Use '-Action status' to inspect running processes." -ForegroundColor Green
        }
        'stop' {
            Write-Host "[kitsu] Stop signals dispatched to all services." -ForegroundColor Green
        }
        'status' {
            Write-Host "[kitsu] Status check completed." -ForegroundColor Green
        }
    }
    exit 0
} finally {
    if ($null -ne $originalLogRoot) {
        $env:KITSU_LOG_ROOT = $originalLogRoot
    } else {
        Remove-Item Env:KITSU_LOG_ROOT -ErrorAction SilentlyContinue
    }
}
