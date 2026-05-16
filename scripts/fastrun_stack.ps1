# Stack dogrulama + bot Vault baglantisi
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
Remove-Item Env:VAULT_ADDR -ErrorAction SilentlyContinue
docker compose up -d --build bot 2>&1 | Out-Null
Start-Sleep 25
docker exec super_otonom_bot python -c @"
from super_otonom.vault_bridge import VaultBridge
v = VaultBridge()
s = v.status()
k = v.get_secret('binance', 'api_key')
print('vault_ok', s.get('available'))
print('has_key', bool(k))
print('placeholder', str(k).startswith('GERCEK'))
"@
Write-Host "fastrun_stack: bitti. placeholder=true ise gercek Binance key vault'a yazin."
