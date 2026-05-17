# P0.9+ yerel kapilar: security + go_live (+ opsiyonel vault/obs)
param(
    [switch]$SkipVault,
    [switch]$SkipObservability
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_p09: P0.9+ bant dogrulama"
Write-Host "  Plan: docs/P09_BANDS.md"
Write-Host ""

powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\fastrun_security.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\fastrun_go_live.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\fastrun_survivorship.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\fastrun_ha.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\fastrun_clock_skew.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipVault) {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-Host ""
        Write-Host "=== Vault (opsiyonel) ==="
        Write-Host "  Tam kurulum: scripts\fastrun_vault.cmd"
        $vaultRunning = docker ps --format "{{.Names}}" 2>$null | Select-String "super_otonom_vault"
        if ($vaultRunning) {
            powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\vault_seed_host.ps1"
            if ($LASTEXITCODE -ne 0) {
                Write-Host "UYARI: vault_seed atlandi/basarisiz - scripts\vault_seed.cmd"
            }
        } else {
            Write-Host "UYARI: Vault container yok - scripts\fastrun_vault.cmd"
        }
    }
}

if (-not $SkipObservability) {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-Host ""
        Write-Host "=== Observability (opsiyonel, Docker) ==="
        Write-Host "  Calistirmak icin: scripts/fastrun_observability.ps1"
    }
}

Write-Host ""
Write-Host "fastrun_p09: kod kapilari tamam."
Write-Host "  Sonraki surec PR: INSTITUTIONAL checklist, backup_daily, branch protection"
Write-Host "  Yedek dry-run: powershell -File scripts/backup_daily.ps1 -DryRun"
