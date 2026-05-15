# Observability: Prometheus + Alertmanager + Grafana + Telegram bridge + bot
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$compose = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")
$tgLocal = Join-Path $root "data\local\telegram.env"

if (Test-Path $tgLocal) {
    Write-Host "[0/5] telegram.env -> .env + Vault..."
    powershell -ExecutionPolicy Bypass -File "$root\scripts\setup_telegram_alerts.ps1"
} else {
    Write-Host "[0/5] telegram.env yok - WEBHOOK_URL hazir; Telegram icin telegram.env doldurun."
}

Write-Host "[1/5] stack..."
docker @compose up -d --build alert_telegram alertmanager prometheus grafana bot

Write-Host "[2/5] bagimlilik kontrolu..."
Start-Sleep -Seconds 25
$pyBot = "import importlib.util; from super_otonom.config import _vault_bridge; from super_otonom.timescale_bridge import TimescaleBridge; print('psycopg2', bool(importlib.util.find_spec('psycopg2'))); v=_vault_bridge().status(); print('vault', v.get('available'), v.get('auth')); print('timescale', TimescaleBridge().status().get('available'))"
docker exec super_otonom_bot python -c $pyBot 2>&1 | ForEach-Object { Write-Host "  $_" }

Write-Host "[3/5] Prometheus kurallari..."
Start-Sleep -Seconds 5
try {
    $rules = Invoke-RestMethod -Uri "http://127.0.0.1:9090/api/v1/rules" -TimeoutSec 15
    Write-Host "  rule groups: $(@($rules.data.groups).Count)"
} catch {
    Write-Host "  UYARI: Prometheus henuz hazir degil."
}

Write-Host "[4/5] Bot metrikleri..."
try {
    $m = Invoke-WebRequest -Uri "http://127.0.0.1:8000/metrics" -UseBasicParsing -TimeoutSec 15
    $hits = @(
        "bot_dependency_up",
        "bot_order_errors_total",
        "bot_ws_reconnects_total",
        "bot_peak_drawdown_pct"
    ) | ForEach-Object { if ($m.Content -match $_) { $_ } }
    Write-Host "  metrikler: $($hits -join ', ')"
} catch {
    Write-Host "  UYARI: bot:8000 erisilemedi."
}

Write-Host "[5/5] Alertmanager + Telegram bridge..."
try {
    $h = Invoke-WebRequest -Uri "http://127.0.0.1:8081/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "  alert_telegram health: $($h.StatusCode)"
} catch {
    Write-Host "  UYARI: alert_telegram health erisilemedi."
}
$pyTg = "from super_otonom.alertmanager_telegram_bridge import _telegram_creds; t,c=_telegram_creds(); print('telegram_configured', 1 if t and c else 0)"
docker exec super_otonom_alert_telegram python -c $pyTg 2>&1 | ForEach-Object { Write-Host "  $_" }

$wh = ""
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*WEBHOOK_URL=(.+)$') { $wh = $Matches[1].Trim() }
    }
}
Write-Host "  WEBHOOK_URL: $wh"

Write-Host ""
Write-Host "fastrun_observability: bitti."
Write-Host "  Prometheus: http://127.0.0.1:9090/alerts"
Write-Host "  Alertmanager: http://127.0.0.1:9093"
Write-Host "  Grafana Ops: http://127.0.0.1:3000/d/super-otonom-ops"
Write-Host "  Bot metrics: http://127.0.0.1:8000/metrics"
