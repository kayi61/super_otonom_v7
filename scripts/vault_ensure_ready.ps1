# Vault: container + unseal + host 8200 hazir (dot-source veya -File)
param([string]$Root = "")

$ErrorActionPreference = "Stop"
if (-not $Root) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
Set-Location $Root

$initFile = Join-Path $Root "data\local\vault_init.json"

docker compose up -d vault | Out-Null

$statusJson = $null
for ($i = 0; $i -lt 45; $i++) {
    $statusJson = docker exec super_otonom_vault vault status -format=json 2>$null
    if ($statusJson) { break }
    Start-Sleep -Seconds 2
}
if (-not $statusJson) { throw "Vault container yok - Docker acik mi?" }

function Unseal-VaultFromInit {
    if (-not (Test-Path $initFile)) {
        throw "Vault sealed; data\local\vault_init.json yok. scripts\fastrun_vault.cmd --reset"
    }
    $data = Get-Content $initFile -Raw | ConvertFrom-Json
    docker exec super_otonom_vault vault operator unseal $data.unseal_keys_b64[0] | Out-Null
    Start-Sleep -Seconds 2
}

$st = $statusJson | ConvertFrom-Json
if (-not $st.Initialized) {
    throw "Vault init yok - once: scripts\fastrun_vault.cmd"
}
if ($st.Sealed) {
    Unseal-VaultFromInit
    $st = (docker exec super_otonom_vault vault status -format=json | ConvertFrom-Json)
    if ($st.Sealed) { throw "Vault hala sealed - unseal basarisiz" }
    Write-Host "vault_ensure_ready: unseal OK"
}

$env:VAULT_ADDR = "http://127.0.0.1:8200"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    $st = (docker exec super_otonom_vault vault status -format=json | ConvertFrom-Json)
    if ($st.Sealed) { Unseal-VaultFromInit }
    try {
        $r = Invoke-WebRequest -Uri "$($env:VAULT_ADDR)/v1/sys/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        if ($code -eq 503) {
            Unseal-VaultFromInit
        }
    }
    Start-Sleep -Seconds 2
}
if (-not $ready) { throw "Vault host API hazir degil (503/sealed). docker compose ps vault" }

if (Test-Path $initFile) {
    $env:VAULT_TOKEN = (Get-Content $initFile -Raw | ConvertFrom-Json).root_token
}

Write-Host "vault_ensure_ready: hazir ($($env:VAULT_ADDR))"
