# Ag kilidi: ic servisler dis porta kapali; nginx tek giris; istege bagli TLS
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")
if ((Test-Path "docker\tls\cert.pem") -and (Test-Path "docker\tls\key.pem")) {
    $files += "-f", "docker-compose.tls.yml"
    Write-Host "fastrun_network_lock: TLS overlay (443)"
} else {
    Write-Host "fastrun_network_lock: TLS yok (gen_internal_tls.ps1)"
}
docker compose @files up -d --remove-orphans
$init = Join-Path $root "data\local\vault_init.json"
if (Test-Path $init) {
    $j = Get-Content $init -Raw | ConvertFrom-Json
    if ($j.unseal_keys_b64) {
        Start-Sleep -Seconds 3
        docker exec super_otonom_vault vault operator unseal $j.unseal_keys_b64[0] 2>$null | Out-Null
        Write-Host "fastrun_network_lock: vault unseal OK"
    }
}
docker compose @files up -d bot nginx 2>&1 | Out-Null
Write-Host ""
Write-Host "Erisim (localhost / SSH tunnel):"
Write-Host "  Bot:        http://127.0.0.1/"
Write-Host "  Grafana:    http://127.0.0.1/grafana/"
Write-Host "  Prometheus: http://127.0.0.1:9090"
Write-Host "  Vault UI:   http://127.0.0.1:8200 (dev overlay only)"
Write-Host "  Postgres:   127.0.0.1:5432 (dev overlay only)"
Write-Host "Dis agdan 5432/8200/3000 yayinlanmiyor (default compose)."
