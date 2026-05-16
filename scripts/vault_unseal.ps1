# Yerel gelistirme: Vault konteyner mühürlüyse vault_init.json ile ac (tek share).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$init = Join-Path $root "data\local\vault_init.json"
if (-not (Test-Path $init)) {
    Write-Host "vault_unseal: vault_init.json yok — atlandi."
    exit 0
}
$running = docker inspect -f "{{.State.Running}}" super_otonom_vault 2>$null
if ($running -ne "true") {
    Write-Host "vault_unseal: super_otonom_vault calismiyor — atlandi."
    exit 0
}
try {
    $stJson = docker exec super_otonom_vault vault status -format=json 2>&1
    $st = $stJson | ConvertFrom-Json
    if (-not $st.sealed) {
        Write-Host "vault_unseal: Vault zaten acik."
        exit 0
    }
} catch {
    Write-Host "vault_unseal: vault status okunamadi — unseal deneniyor."
}
$j = Get-Content $init -Raw | ConvertFrom-Json
$key = $j.unseal_keys_hex[0]
docker exec super_otonom_vault vault operator unseal $key | Out-Null
Write-Host "vault_unseal: unseal tamamlandi."
