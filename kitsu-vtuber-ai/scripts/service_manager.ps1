param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$ServiceName,

    [Parameter(Position = 2)]
    [string]$Command,

    [string]$WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,

    [string[]]$ChildProcessNames = @(),

    [int]$ChildDiscoveryTimeoutSeconds = 5
)

$ErrorActionPreference = 'Stop'

$pidRoot = Join-Path (Join-Path $PSScriptRoot '..') '.pids'
if (-not (Test-Path $pidRoot)) {
    New-Item -ItemType Directory -Path $pidRoot -Force | Out-Null
}

$pidFile = Join-Path $pidRoot "$ServiceName.pid"

function Write-Log {
    param(
        [string]$Message
    )

    $timestamp = (Get-Date).ToString('u')
    Write-Host "[$timestamp][$ServiceName] $Message"
}

function Get-ProcessDescendants {
    param(
        [int]$ParentPid
    )

    $descendants = @()
    $queue = @([int]$ParentPid)
    $visited = @{}
    $visited[[int]$ParentPid] = $true
    $index = 0

    while ($index -lt $queue.Count) {
        $current = $queue[$index]
        $index += 1

        try {
            $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $current"
        } catch {
            $children = @()
        }

        foreach ($child in $children) {
            $childPid = [int]$child.ProcessId
            if (-not $visited.ContainsKey($childPid)) {
                $visited[$childPid] = $true
                $descendants += $child
                $queue += $childPid
            }
        }
    }

    return $descendants
}

function Resolve-ChildProcess {
    param(
        [int]$ParentPid
    )

    $deadline = (Get-Date).AddSeconds($ChildDiscoveryTimeoutSeconds)
    $candidateNames = $ChildProcessNames |
        Where-Object { $_ -and $_.Trim() } |
        ForEach-Object { $_.Trim().ToLowerInvariant() }
    $wrapperNames = @('pwsh', 'pwsh.exe', 'powershell', 'powershell.exe', 'cmd', 'cmd.exe', 'conhost', 'conhost.exe', 'poetry', 'poetry.exe')

    do {
        $descendants = Get-ProcessDescendants -ParentPid $ParentPid
        if ($descendants) {
            $sorted = $descendants | Sort-Object {
                try {
                    [System.Management.ManagementDateTimeConverter]::ToDateTime($_.CreationDate)
                } catch {
                    Get-Date '1970-01-01'
                }
            } -Descending

            if ($candidateNames.Count -gt 0) {
                $matches = $sorted | Where-Object {
                    $name = $_.Name
                    $normalized = [System.IO.Path]::GetFileNameWithoutExtension($name).ToLowerInvariant()
                    $candidateNames -contains $normalized -or $candidateNames -contains $name.ToLowerInvariant()
                }

                if ($matches) {
                    $child = $matches | Select-Object -First 1
                    return @{ Pid = $child.ProcessId; Name = $child.Name }
                }
            }

            $nonWrapper = $sorted | Where-Object {
                $wrapperNames -notcontains $_.Name.ToLowerInvariant()
            }

            $fallback = if ($nonWrapper) { $nonWrapper | Select-Object -First 1 } else { $sorted | Select-Object -First 1 }

            if ($fallback) {
                return @{ Pid = $fallback.ProcessId; Name = $fallback.Name }
            }
        }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)

    return $null
}

switch ($Action) {
    'start' {
        if (-not $Command) {
            throw "Forneça um comando via -Command ao iniciar o serviço."
        }

        if (Test-Path $pidFile) {
            Write-Log "Já existe um PID registrado em $pidFile. Execute 'stop' antes de iniciar novamente."
            exit 1
        }

        $shellCmd = Get-Command pwsh -ErrorAction SilentlyContinue
        $shellExe = if ($shellCmd) { $shellCmd.Source } else { (Get-Command powershell.exe -ErrorAction Stop).Source }

        $argList = @('-NoLogo', '-NoExit', '-Command', $Command)

        Write-Log "Inicializando serviço com comando: $Command"
        $parentProcess = Start-Process -FilePath $shellExe -ArgumentList $argList -WorkingDirectory $WorkingDirectory -WindowStyle Minimized -PassThru
        Write-Log "Processo pai iniciado (PID=$($parentProcess.Id)). Aguardando worker filho..."

        $childInfo = Resolve-ChildProcess -ParentPid $parentProcess.Id
        $workerPid = if ($childInfo) { $childInfo.Pid } else { $parentProcess.Id }
        $workerName = if ($childInfo) { $childInfo.Name } else { $parentProcess.ProcessName }

        if ($childInfo) {
            Write-Log "Worker identificado: $workerName (PID=$workerPid)."
        } else {
            Write-Log "Nenhum worker filho encontrado; usando PID do wrapper ($workerPid)."
        }

        $payload = [ordered]@{
            service             = $ServiceName
            started_at          = (Get-Date).ToString('o')
            command             = $Command
            working_directory   = $WorkingDirectory
            parent_pid          = $parentProcess.Id
            parent_process_name = $parentProcess.ProcessName
            worker_pid          = $workerPid
            worker_process_name = $workerName
            child_process_names = $ChildProcessNames
        }

        $payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $pidFile -Encoding UTF8
        Write-Log "PID persistido em $pidFile."
    }
    'stop' {
        if (-not (Test-Path $pidFile)) {
            Write-Log "Nenhum PID encontrado em $pidFile. Nada a fazer."
            break
        }

        $info = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $pidsToStop = @()
        if ($info.worker_pid) { $pidsToStop += [int]$info.worker_pid }
        if ($info.parent_pid -and $info.parent_pid -ne $info.worker_pid) { $pidsToStop += [int]$info.parent_pid }

        $uniquePids = $pidsToStop | Select-Object -Unique
        foreach ($pid in $uniquePids) {
            try {
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Log "Encerrando processo PID=$pid."
                    Stop-Process -Id $pid -Force -ErrorAction Stop
                } else {
                    Write-Log "PID $pid já não está em execução."
                }
            } catch {
                Write-Log "Aviso: não foi possível encerrar PID=$pid ($($_.Exception.Message))."
            }
        }

        $stillRunning = $false
        foreach ($pid in $uniquePids) {
            if (Get-Process -Id $pid -ErrorAction SilentlyContinue) {
                $stillRunning = $true
                break
            }
        }

        if ($stillRunning) {
            Write-Log "Ainda existem processos ativos; mantendo $pidFile para inspeção."
        } else {
            Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
            Write-Log "Arquivo de PID removido."
        }
    }
    'status' {
        if (-not (Test-Path $pidFile)) {
            Write-Log "Serviço parado (PID file ausente)."
            break
        }

        $info = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $workerRunning = if ($info.worker_pid) { Get-Process -Id $info.worker_pid -ErrorAction SilentlyContinue } else { $null }
        $parentRunning = if ($info.parent_pid) { Get-Process -Id $info.parent_pid -ErrorAction SilentlyContinue } else { $null }
        $status = if ($workerRunning) { 'em execução' } elseif ($parentRunning) { 'wrapper ativo, worker ausente' } else { 'parado' }
        Write-Log "Status: $status (worker PID=$($info.worker_pid), wrapper PID=$($info.parent_pid))."
    }
}
