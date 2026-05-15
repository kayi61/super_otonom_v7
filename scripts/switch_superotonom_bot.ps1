# Eski bot (SuperOtonomBot_bot) token ile projeyi guncelle — tek seferlik
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "1) BotFather: /mybots -> SuperOtonomBot_bot -> API Token"
Write-Host "2) Token'i kopyala; asagiya yapistir (Enter):"
$tok = Read-Host "TELEGRAM_BOT_TOKEN"
$chat = "1563530428"
if (-not ($tok -match '^\d+:.+')) { throw "Gecersiz token formati" }

$local = Join-Path $root "data\local\telegram.env"
@(
    "TELEGRAM_BOT_TOKEN=$tok"
    "TELEGRAM_CHAT_ID=$chat"
) | Set-Content $local -Encoding utf8

powershell -ExecutionPolicy Bypass -File "$root\scripts\setup_telegram_alerts.ps1"
powershell -ExecutionPolicy Bypass -File "$root\scripts\fastrun_observability.ps1"

Write-Host "Test mesaji..."
docker exec super_otonom_alert_telegram python -c "from super_otonom.alertmanager_telegram_bridge import _send_telegram; print('send', _send_telegram('Super Otonom: eski bot (SuperOtonomBot) aktif.'))"
