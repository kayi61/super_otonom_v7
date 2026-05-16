# .env: API anahtarlarini ve VAULT_TOKEN'i kaldir; zayif DB parolalarini yenile; Vault AppRole alanlari ekle.
# Degerler stdout'a yazilmaz. Calistir: powershell -File scripts/env_harden_secrets.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) { throw ".env yok: $envPath" }

$apiKeys = @(
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_KEY", "BINANCE_SECRET_KEY", "BINANCE_SECRET",
    "BYBIT_API_KEY", "BYBIT_API_SECRET", "OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSWORD",
    "KUCOIN_API_KEY", "KUCOIN_API_SECRET", "KUCOIN_API_PASSPHRASE",
    "COINBASE_API_KEY", "COINBASE_API_SECRET", "GATEIO_API_KEY", "GATEIO_API_SECRET",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "VAULT_TOKEN"
)
$weak = @("Elif.6134", "changeme", "password", "admin")
$pwVars = @("POSTGRES_PASSWORD", "GRAFANA_PASSWORD", "TIMESCALE_PASSWORD")

function New-RandPw { return [Convert]::ToBase64String((1..18 | ForEach-Object { Get-Random -Maximum 256 })) }

$lines = Get-Content $envPath -Encoding UTF8
$out = [System.Collections.Generic.List[string]]::new()
$seen = @{}
$vaultBlock = $false

foreach ($line in $lines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $key = $Matches[1]
        $val = $Matches[2].Trim()
        if ($apiKeys -contains $key) { continue }
        if ($pwVars -contains $key -and $val -in $weak) {
            $line = "$key=$(New-RandPw)"
            $val = ""
        }
        if ($seen[$key]) { continue }
        $seen[$key] = $true
    }
    $out.Add($line)
}
# Kalan zayif parolalar (yinelenen anahtar satirlari atlanmissa)
for ($i = 0; $i -lt $out.Count; $i++) {
    if ($out[$i] -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $key = $Matches[1]
        $val = $Matches[2].Trim()
        if ($pwVars -contains $key -and $val -in $weak) {
            $out[$i] = "$key=$(New-RandPw)"
        }
    }
}

$need = @{
    "VAULT_ADDR" = "http://vault:8200"
    "VAULT_ROLE_ID" = ""
    "VAULT_SECRET_ID" = ""
    "VAULT_MOUNT" = "secret"
    "VAULT_BASE_PATH" = "trading"
    "SECRETS_VAULT_ONLY" = ""
    "SECRETS_VAULT_ONLY_AUTO" = "true"
}
$insertAt = -1
for ($i = 0; $i -lt $out.Count; $i++) {
    if ($out[$i] -match 'VAULT_ADDR=') { $insertAt = $i; break }
}
if ($insertAt -lt 0) {
    $out.Add("")
    $out.Add("# ---- Vault ----")
    $insertAt = $out.Count
}
$block = @()
foreach ($k in $need.Keys) {
    if (-not $seen[$k]) { $block += "$k=$($need[$k])" }
}
if ($block.Count -gt 0) {
    $pos = $insertAt + 1
    foreach ($b in $block) { $out.Insert($pos, $b); $pos++ }
}

# Timescale = Postgres (Docker ayni kullanici/parola)
$pg = ($out | Where-Object { $_ -match '^POSTGRES_PASSWORD=' } | Select-Object -First 1)
if ($pg) {
    for ($i = 0; $i -lt $out.Count; $i++) {
        if ($out[$i] -match '^TIMESCALE_PASSWORD=') { $out[$i] = $pg -replace '^POSTGRES_', 'TIMESCALE_' }
    }
}

Set-Content -Path $envPath -Value $out -Encoding UTF8
Write-Host "env_harden_secrets: .env guncellendi (API anahtarlari + VAULT_TOKEN kaldirildi; zayif parolalar yenilendi)."
Write-Host "Sonraki: docker compose up -d vault; scripts/vault_bootstrap.ps1; python -m super_otonom.vault_seed"
