param(
    [Parameter(Mandatory = $true)][string]$ServiceName,
    [Parameter(Mandatory = $true)][string[]]$Command,
    [ValidateSet("start", "stop", "status")][string]$Action = "start",
    [string]$Description = "",
    [string]$Executable = "poetry"
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stateDir = Join-Path $repoRoot 'scripts/.service-state'
if (-not (Test-Path $stateDir)) {
    New-Item -Path $stateDir -ItemType Directory | Out-Null
}
$pidFile = Join-Path $stateDir ("{0}.pid" -f $ServiceName)

function Get-ServiceProcess {
    param([int]$Pid)

    try {
        return Get-Process -Id $Pid -ErrorAction Stop
    } catch {
        return $null
    }
}

switch ($Action) {
    'start' {
        if (Test-Path $pidFile) {
            $existingPid = [int](Get-Content $pidFile)
            $proc = Get-ServiceProcess -Pid $existingPid
            if ($proc) {
                Write-Warning "Service '$ServiceName' is already running (PID $existingPid)."
                return
            }
        }

        Write-Host "[kitsu] Starting $ServiceName..." -ForegroundColor Cyan
        try {
            $process = Start-Process -FilePath $Executable -ArgumentList $Command -PassThru -WorkingDirectory $repoRoot -WindowStyle Normal
            Set-Content -Path $pidFile -Value $process.Id
            Write-Host "[kitsu] $ServiceName started with PID $($process.Id)."
        } catch {
            Write-Error "Failed to start $ServiceName: $($_.Exception.Message)"
        }
    }
    'stop' {
        if (-not (Test-Path $pidFile)) {
            Write-Warning "No PID file found for '$ServiceName'. Nothing to stop."
            return
        }

        $pid = [int](Get-Content $pidFile)
        $process = Get-ServiceProcess -Pid $pid
        if (-not $process) {
            Write-Warning "Process $pid for '$ServiceName' is no longer running. Cleaning up PID file."
            Remove-Item $pidFile -ErrorAction SilentlyContinue
            return
        }

        Write-Host "[kitsu] Stopping $ServiceName (PID $pid)..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $pid -ErrorAction Stop
            Write-Host "[kitsu] $ServiceName stopped."
        } catch {
            Write-Error "Failed to stop $ServiceName: $($_.Exception.Message)"
        }

        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
    'status' {
        if (-not (Test-Path $pidFile)) {
            Write-Host "[kitsu] $ServiceName is stopped." -ForegroundColor DarkGray
            if ($Description) {
                Write-Host "        $Description"
            }
            return
        }

        $pid = [int](Get-Content $pidFile)
        $process = Get-ServiceProcess -Pid $pid
        if ($process) {
            Write-Host "[kitsu] $ServiceName running (PID $pid)." -ForegroundColor Green
        } else {
            Write-Host "[kitsu] $ServiceName has a stale PID file (PID $pid)." -ForegroundColor DarkYellow
            Remove-Item $pidFile -ErrorAction SilentlyContinue
        }

        if ($Description) {
            Write-Host "        $Description"
        }
    }
}
