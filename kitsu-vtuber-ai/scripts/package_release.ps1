[CmdletBinding()]
param(
    [string]$OutputPath = "artifacts/release",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $repoRoot "..").Path
Push-Location $projectRoot

if (-not (Test-Path $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleName = "kitsu-release-$timestamp"
$bundleRoot = Join-Path $OutputPath $bundleName
New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null

$itemsToCopy = @(
    "README.md",
    "RUN_FIRST.md",
    "execplan.md",
    ".env.example",
    "poetry.lock",
    "pyproject.toml",
    "licenses",
    "scripts",
    "configs",
    "apps"
)

foreach ($item in $itemsToCopy) {
    $source = Join-Path "kitsu-vtuber-ai" $item
    if (Test-Path $source) {
        Copy-Item $source -Destination $bundleRoot -Recurse -Force
    }
}

Copy-Item "kitsu-vtuber-ai/RUN_FIRST.md" -Destination $bundleRoot -Force
Copy-Item "kitsu-vtuber-ai/README.md" -Destination $bundleRoot -Force
Copy-Item "kitsu-vtuber-ai/.env.example" -Destination $bundleRoot -Force

$notes = @()
$notes += "Release gerada em $([DateTime]::UtcNow.ToString('u'))"
$notes += "Scripts inclusos: run_all_no_docker.ps1, service_manager.ps1, package_release.ps1"
$notes += "Consulte RUN_FIRST.md (seções 9-12) para checklist de QA e piloto."
$notes += "Licenças obrigatórias em licenses/third_party/"
$notesPath = Join-Path $bundleRoot "RELEASE_NOTES.txt"
$notes | Set-Content -Path $notesPath -Encoding UTF8

if ($Zip) {
    $zipPath = "$bundleRoot.zip"
    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $bundleRoot '*') -DestinationPath $zipPath -Force
    Write-Host "Pacote ZIP gerado em $zipPath"
} else {
    Write-Host "Bundle disponível em $bundleRoot"
}

Pop-Location
