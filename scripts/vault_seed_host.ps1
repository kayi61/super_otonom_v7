# Host uzerinden vault_seed: unseal + .env/telegram.env yukle + seed
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

. "$root\scripts\vault_ensure_ready.ps1" -Root $root

function Import-EnvFile([string]$path) {
    if (-not (Test-Path $path)) { return }
    $skip = @("VAULT_ADDR")
    Get-Content $path -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $k = $Matches[1]
            if ($skip -contains $k) { return }
            $v = $Matches[2].Trim().Trim('"').Trim("'")
            if ($v) { Set-Item -Path "Env:$k" -Value $v }
        }
    }
}

Import-EnvFile (Join-Path $root ".env")
Import-EnvFile (Join-Path $root "data\local\telegram.env")

$init = Join-Path $root "data\local\vault_init.json"
$env:VAULT_ADDR = "http://127.0.0.1:8200"
if (Test-Path $init) {
    $env:VAULT_TOKEN = (Get-Content $init -Raw | ConvertFrom-Json).root_token
}

python -m super_otonom.vault_seed
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "vault_seed_host: basarisiz."
    Write-Host "  - .env veya data\local\telegram.env icinde BINANCE_* / TELEGRAM_* olmali"
    Write-Host "  - env_harden anahtarlari sildiyse gecici olarak geri yazin, seed, sonra env_harden_secrets.cmd"
    exit $LASTEXITCODE
}
Write-Host "vault_seed_host: OK - istege bagli: scripts\env_harden_secrets.cmd"
