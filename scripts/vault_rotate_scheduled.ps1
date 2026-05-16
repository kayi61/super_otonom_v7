# Gorev Zamanlayici icin: AppRole secret aylik rotate (admin token ile)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
python -m super_otonom.vault_rotate --approle
docker compose restart bot | Out-Null
Write-Host "vault_rotate_scheduled: OK"
