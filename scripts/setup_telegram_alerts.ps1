# Telegram -> .env + Vault + WEBHOOK_URL
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

try {
    powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\vault_unseal.ps1"
} catch {
    Write-Host "vault_unseal atlandi: $_"
}

$local = Join-Path $root "data\local\telegram.env"
$envPath = Join-Path $root ".env"
if (-not (Test-Path $local)) {
    Write-Host "telegram.env yok. Ornek: data\local\telegram.env.example -> telegram.env"
    exit 1
}

$tok = ""; $chat = ""
Get-Content $local | ForEach-Object {
    if ($_ -match '^\s*TELEGRAM_BOT_TOKEN=(.+)$') { $tok = $Matches[1].Trim() }
    if ($_ -match '^\s*TELEGRAM_CHAT_ID=(.+)$') { $chat = $Matches[1].Trim() }
}
if (-not $tok -or -not $chat) { throw "telegram.env icinde TOKEN ve CHAT_ID gerekli" }

function Set-EnvLine($key, $val) {
    $lines = @(Get-Content $envPath -ErrorAction SilentlyContinue)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$key=") { $found = $true; "$key=$val" } else { $line }
    }
    if (-not $found) { $out += "$key=$val" }
    $out | Set-Content $envPath -Encoding utf8
}

Set-EnvLine "TELEGRAM_BOT_TOKEN" $tok
Set-EnvLine "TELEGRAM_CHAT_ID" $chat
Set-EnvLine "WEBHOOK_URL" "http://alert_telegram:8081/alert"
Set-EnvLine "ALERTMANAGER_WEBHOOK_URL" "http://alert_telegram:8081/alert"

$env:TELEGRAM_BOT_TOKEN = $tok
$env:TELEGRAM_CHAT_ID = $chat
$env:VAULT_ADDR = "http://127.0.0.1:8200"
$init = Join-Path $root "data\local\vault_init.json"
if (Test-Path $init) {
    $env:VAULT_TOKEN = (Get-Content $init -Raw | ConvertFrom-Json).root_token
}
python -c @"
from super_otonom.vault_bridge import VaultBridge
vb = VaultBridge()
if vb.status().get('available'):
    vb.put_secret('telegram', {'bot_token': '$tok', 'chat_id': '$chat'})
    print('vault telegram OK')
"@

Write-Host "setup_telegram_alerts: .env + Vault guncellendi."
