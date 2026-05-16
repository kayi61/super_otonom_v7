# Tek komut: Vault stack + bootstrap + seed (Docker acik olmali)
# Sira: bootstrap -> seed (.env/telegram.env) -> env_harden
# Calistir: scripts\fastrun_vault.cmd  (ExecutionPolicy Bypass)
param([switch]$SkipHarden)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "[1/4] vault container..."
docker compose up -d vault
Start-Sleep -Seconds 5

Write-Host "[2/4] AppRole bootstrap..."
python -m super_otonom.vault_bootstrap_docker --reset
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/4] API anahtarlarini Vault'a seed (.env / telegram.env)..."
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\vault_seed_host.ps1"
$seedExit = $LASTEXITCODE
if ($seedExit -ne 0) {
    Write-Host "UYARI: vault_seed basarisiz - anahtarlari .env veya data\local\telegram.env dosyasina gecici ekleyin."
    Write-Host "  Sonra: scripts\vault_seed.cmd"
}

if (-not $SkipHarden) {
    Write-Host "[4/4] .env sertlestirme (seed basariliysa)..."
    if ($seedExit -eq 0) {
        powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\env_harden_secrets.ps1"
    } else {
        Write-Host "  env_harden atlandi (once vault_seed basarili olmali)"
    }
} else {
    Write-Host "[4/4] env_harden atlandi (-SkipHarden)"
}

if ($seedExit -ne 0) { exit $seedExit }
Write-Host "fastrun_vault: bitti. docker compose up -d ile botu baslatin."
