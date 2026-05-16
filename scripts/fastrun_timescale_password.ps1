# Timescale parola uyumu: .env -> volume (ALTER USER) veya --reset-volume
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
python -m super_otonom.timescale_password_migrate
# TIMESCALE_PASSWORD = POSTGRES_PASSWORD (.env'de zaten esitlenmeli)
docker compose up -d timescaledb bot grafana 2>&1 | Out-Null
Write-Host "fastrun_timescale_password: OK"
