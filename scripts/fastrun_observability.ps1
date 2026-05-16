# Observability: Prometheus + Alertmanager + Grafana + Telegram bridge + bot + drill (PROMPT 3)
param(
    [switch]$SkipStack,
    [switch]$SkipPytest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (-not $SkipStack) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "HATA: Docker yok — observability stack baslatilamaz."
        exit 1
    }

    try {
        powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\vault_unseal.ps1"
    } catch {
        Write-Host "[vault_unseal] UYARI: $_"
    }

    $compose = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")
    $tgLocal = Join-Path $root "data\local\telegram.env"

    if (Test-Path $tgLocal) {
        Write-Host "[0/6] telegram.env -> .env + Vault..."
        powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\setup_telegram_alerts.ps1"
    } else {
        Write-Host "[0/6] telegram.env yok — drill Telegram adimi FAIL olabilir."
        Write-Host "      Ornek: data\local\telegram.env icinde TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID"
    }

    Write-Host "[1/6] stack (prometheus, alertmanager, alert_telegram, grafana, bot)..."
    docker @compose up -d --build alert_telegram alertmanager prometheus grafana bot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "[2/6] bagimlilik kontrolu (bot container)..."
    Start-Sleep -Seconds 25
    $pyBot = "import importlib.util; from super_otonom.config import _vault_bridge; from super_otonom.timescale_bridge import TimescaleBridge; print('psycopg2', bool(importlib.util.find_spec('psycopg2'))); v=_vault_bridge().status(); print('vault', v.get('available'), v.get('auth')); print('timescale', TimescaleBridge().status().get('available'))"
    docker exec super_otonom_bot python -c $pyBot 2>&1 | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "fastrun_observability: -SkipStack — yalnizca drill"
}

Write-Host ""
Write-Host "[6/6] observability_drill (metrik + kasitli Telegram testi)..."
python -m super_otonom.observability_drill
$drillExit = $LASTEXITCODE

if (-not $SkipPytest) {
    Write-Host ""
    python -m pytest tests/test_observability_drill_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
if ($drillExit -eq 0) {
    Write-Host "fastrun_observability: PASS — docs\OBSERVABILITY_DRILL.md"
} else {
    Write-Host "fastrun_observability: FAIL (drill) — Telegram/env/stack kontrol edin"
}
Write-Host "  Prometheus: http://127.0.0.1:9090/alerts"
Write-Host "  Grafana:    http://127.0.0.1:3000/d/super-otonom-ops"
exit $drillExit
