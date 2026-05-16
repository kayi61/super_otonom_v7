# Vault dev bootstrap: KV v2 + AppRole (super_otonom_bot)
param(
    [string]$Container = "super_otonom_vault",
    [string]$Mount = "secret",
    [string]$BasePath = "trading",
    [switch]$ResetIfSealed
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$compose = Join-Path $root "docker-compose.yml"
$initFile = Join-Path $root "data\local\vault_init.json"

function Invoke-VaultCmd([string[]]$Cmd) {
    if (-not $Cmd -or $Cmd.Count -eq 0) { throw "Invoke-VaultCmd: empty command" }
    $dockerArgs = @("exec", "-e", "VAULT_ADDR=http://127.0.0.1:8200")
    if ($env:VAULT_TOKEN) { $dockerArgs += @("-e", "VAULT_TOKEN=$($env:VAULT_TOKEN)") }
    $dockerArgs += @($Container, "vault") + $Cmd
    $out = & docker @dockerArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw ($out | Out-String).Trim() }
    return $out
}

function Reset-VaultDev {
    Write-Host "vault_bootstrap: dev vault volume reset..."
    docker compose -f $compose rm -sf vault | Out-Null
    $vol = docker volume ls --format "{{.Name}}" | Where-Object { $_ -match "vault_data" } | Select-Object -First 1
    if ($vol) { docker volume rm $vol -f | Out-Null }
    docker compose -f $compose up -d vault | Out-Null
    Start-Sleep -Seconds 6
    if (Test-Path $initFile) { Remove-Item $initFile -Force }
}

$status = (Invoke-VaultCmd @("status", "-format=json") | Out-String).Trim() | ConvertFrom-Json

if ($status.initialized -and $status.sealed -and $ResetIfSealed) {
    Reset-VaultDev
    $status = (Invoke-VaultCmd @("status", "-format=json") | Out-String).Trim() | ConvertFrom-Json
}

if (-not $status.initialized) {
    Write-Host "Vault init..."
    $initJson = (Invoke-VaultCmd @("operator", "init", "-key-shares=1", "-key-threshold=1", "-format=json") | Out-String).Trim()
    $init = $initJson | ConvertFrom-Json
    $initDir = Split-Path $initFile -Parent
    if (-not (Test-Path $initDir)) { New-Item -ItemType Directory -Path $initDir -Force | Out-Null }
    $init | ConvertTo-Json | Set-Content -Path $initFile -Encoding UTF8
    $env:VAULT_TOKEN = $init.root_token
    Invoke-VaultCmd @("operator", "unseal", $init.unseal_keys_b64[0]) | Out-Null
} elseif ($status.sealed) {
    if (-not (Test-Path $initFile)) { throw "Vault sealed; vault_init.json missing. Use -ResetIfSealed" }
    $init = Get-Content $initFile -Raw | ConvertFrom-Json
    $env:VAULT_TOKEN = $init.root_token
    Invoke-VaultCmd @("operator", "unseal", $init.unseal_keys_b64[0]) | Out-Null
} elseif (Test-Path $initFile) {
    $init = Get-Content $initFile -Raw | ConvertFrom-Json
    $env:VAULT_TOKEN = $init.root_token
} elseif ($ResetIfSealed) {
    Reset-VaultDev
    & $MyInvocation.MyCommand.Path -Container $Container -Mount $Mount -BasePath $BasePath
    return
} else {
    throw "Vault initialized but vault_init.json missing. Use -ResetIfSealed"
}

Invoke-VaultCmd @("secrets", "enable", "-path=$Mount", "-version=2") 2>$null | Out-Null

$policy = @"
path "$Mount/data/$BasePath/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "$Mount/metadata/$BasePath/*" {
  capabilities = ["list", "read"]
}
"@
$policy | docker exec -i $Container sh -c 'cat > /tmp/bot-policy.hcl'
Invoke-VaultCmd @("policy", "write", "super_otonom_bot", "/tmp/bot-policy.hcl") | Out-Null
Invoke-VaultCmd @("auth", "enable", "approle") 2>$null | Out-Null
Invoke-VaultCmd @("write", "auth/approle/role/super_otonom_bot", "token_policies=super_otonom_bot", "token_ttl=1h", "token_max_ttl=4h") | Out-Null

$roleId = (Invoke-VaultCmd @("read", "-field=role_id", "auth/approle/role/super_otonom_bot/role-id") | Out-String).Trim()
$secretId = (Invoke-VaultCmd @("write", "-f", "-field=secret_id", "auth/approle/role/super_otonom_bot/secret-id") | Out-String).Trim()

$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    $lines = Get-Content $envFile -Encoding UTF8
    $map = @{
        "VAULT_ADDR" = "http://vault:8200"
        "VAULT_ROLE_ID" = $roleId
        "VAULT_SECRET_ID" = $secretId
        "VAULT_MOUNT" = $Mount
        "VAULT_BASE_PATH" = $BasePath
    }
    $done = @{}
    $out = foreach ($line in $lines) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=') {
            $k = $Matches[1]
            if ($map.ContainsKey($k)) { $done[$k] = $true; "$k=$($map[$k])"; continue }
            if ($k -eq "VAULT_TOKEN") { continue }
        }
        $line
    }
    foreach ($k in $map.Keys) {
        if (-not $done[$k]) { $out += "$k=$($map[$k])" }
    }
    Set-Content -Path $envFile -Value $out -Encoding UTF8
    Write-Host "vault_bootstrap: .env updated (AppRole)."
}
Write-Host "vault_bootstrap: OK"
