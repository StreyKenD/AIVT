param(
    [Parameter(Mandatory = $true)][string]$ServiceName,
    [Parameter(Mandatory = $true)][string[]]$Command,
    [ValidateSet("start", "stop", "status")][string]$Action = "start",
    [string]$Description = "",
    [string]$Executable = "poetry",
    [string]$LogDirectory
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stateDir = Join-Path $repoRoot 'scripts/.service-state'
if (-not (Test-Path $stateDir)) {
    New-Item -Path $stateDir -ItemType Directory | Out-Null
}
$pidFile = Join-Path $stateDir ("{0}.pid" -f $ServiceName)
$metaFile = Join-Path $stateDir ("{0}.json" -f $ServiceName)

function Resolve-LogDirectory {
    param([string]$RequestedPath)

    $envOverride = $env:KITSU_LOG_ROOT
    $effective = if ($RequestedPath) {
        $RequestedPath
    } elseif ($envOverride) {
        $envOverride
    } else {
        Join-Path $repoRoot 'logs'
    }

    if (-not (Test-Path $effective)) {
        New-Item -ItemType Directory -Path $effective -Force | Out-Null
    }

    return (Resolve-Path -Path $effective).Path
}

function Get-ServiceProcess {
    param([int]$ProcessId)

    try {
        return Get-Process -Id $ProcessId -ErrorAction Stop
    } catch {
        return $null
    }
}

switch ($Action) {
    'start' {
        if (Test-Path $pidFile) {
            $existingPid = [int](Get-Content $pidFile)
            $proc = Get-ServiceProcess -ProcessId $existingPid
            if ($proc) {
                Write-Warning "Service '${ServiceName}' is already running (PID $existingPid)."
                return
            }
        }

        Write-Host "[kitsu] Starting ${ServiceName}..." -ForegroundColor Cyan
        $stdoutLog = $null
        $stderrLog = $null

        if ($Command.Length -eq 0) {
            throw "Command argument list for '${ServiceName}' cannot be empty."
        }

        try {
            $logsRoot = Resolve-LogDirectory -RequestedPath $LogDirectory
            $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
            $logPrefix = Join-Path $logsRoot ("{0}_{1}" -f $ServiceName, $timestamp)
            $stdoutLog = "${logPrefix}.out.log"
            $stderrLog = "${logPrefix}.err.log"
        } catch {
            throw "Failed to prepare log directory for '${ServiceName}': $($_.Exception.Message)"
        }

        try {
            $process = Start-Process -FilePath $Executable -ArgumentList $Command -PassThru -WorkingDirectory $repoRoot -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
            Set-Content -Path $pidFile -Value $process.Id
            $metadata = [ordered]@{
                stdout    = $stdoutLog
                stderr    = $stderrLog
                startedAt = (Get-Date).ToString('o')
            }
            $metadata | ConvertTo-Json | Set-Content -Path $metaFile
            Write-Host "[kitsu] ${ServiceName} started with PID $($process.Id)."
            Write-Host "        stdout → $stdoutLog" -ForegroundColor DarkGray
            Write-Host "        stderr → $stderrLog" -ForegroundColor DarkGray
        } catch {
            Write-Error "Failed to start ${ServiceName}: $($_.Exception.Message)"
            if (Test-Path $stdoutLog) { Remove-Item $stdoutLog -ErrorAction SilentlyContinue }
            if (Test-Path $stderrLog) { Remove-Item $stderrLog -ErrorAction SilentlyContinue }
            if (Test-Path $metaFile) { Remove-Item $metaFile -ErrorAction SilentlyContinue }
            throw
        }
    }
    'stop' {
        if (-not (Test-Path $pidFile)) {
            Write-Warning "No PID file found for '${ServiceName}'. Nothing to stop."
            return
        }

        $servicePid = [int](Get-Content $pidFile)
        $process = Get-ServiceProcess -ProcessId $servicePid
        if (-not $process) {
            Write-Warning "Process $servicePid for '${ServiceName}' is no longer running. Cleaning up PID file."
            Remove-Item $pidFile -ErrorAction SilentlyContinue
            return
        }

        Write-Host "[kitsu] Stopping ${ServiceName} (PID $servicePid)..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $servicePid -ErrorAction Stop
            Write-Host "[kitsu] ${ServiceName} stopped."
        } catch {
            Write-Error "Failed to stop ${ServiceName}: $($_.Exception.Message)"
            throw
        }

        Remove-Item $pidFile -ErrorAction SilentlyContinue
        Remove-Item $metaFile -ErrorAction SilentlyContinue
    }
    'status' {
        if (-not (Test-Path $pidFile)) {
            Write-Host "[kitsu] ${ServiceName} is stopped." -ForegroundColor DarkGray
            if ($Description) {
                Write-Host "        $Description"
            }
            if (Test-Path $metaFile) {
                Remove-Item $metaFile -ErrorAction SilentlyContinue
            }
            return
        }

        $servicePid = [int](Get-Content $pidFile)
        $process = Get-ServiceProcess -ProcessId $servicePid
        if ($process) {
            Write-Host "[kitsu] ${ServiceName} running (PID $servicePid)." -ForegroundColor Green
            if (Test-Path $metaFile) {
                try {
                    $meta = Get-Content $metaFile | ConvertFrom-Json
                    if ($meta.stdout) {
                        Write-Host "        stdout → $($meta.stdout)" -ForegroundColor DarkGray
                    }
                    if ($meta.stderr) {
                        Write-Host "        stderr → $($meta.stderr)" -ForegroundColor DarkGray
                    }
                    if ($meta.startedAt) {
                        Write-Host "        started → $($meta.startedAt)" -ForegroundColor DarkGray
                    }
                } catch {
                    Write-Warning "Unable to read metadata for '${ServiceName}': $($_.Exception.Message)"
                }
            }
        } else {
            Write-Host "[kitsu] ${ServiceName} has a stale PID file (PID $servicePid)." -ForegroundColor DarkYellow
            Remove-Item $pidFile -ErrorAction SilentlyContinue
            Remove-Item $metaFile -ErrorAction SilentlyContinue
        }

        if ($Description) {
            Write-Host "        $Description"
        }
    }
}
