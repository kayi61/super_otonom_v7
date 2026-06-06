# vault_unseal.ps1 - Yerel gelistirme: muhurlu Vault konteynerini vault_init.json ile acar.
#
# ONEMLI: bu dosya SADECE ASCII karakter icerir. PowerShell 5.1 (Windows) .ps1
# dosyalarini sistem ANSI kod sayfasiyla (cp1254/Turkce) okur; UTF-8 em-dash veya
# Turkce karakter parse'i bozar ("string is missing the terminator" / brace hatasi).
# ASCII-only kalmasi BU bug'in tekrar etmemesini garanti eder.
#
# Dayaniklilik: unseal_threshold kadar anahtar gonderir; hex yoksa b64 dener;
# Vault konteyneri yanit verene kadar kisa sure bekler.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$init = Join-Path $root "data\local\vault_init.json"
$container = $env:VAULT_CONTAINER
if ([string]::IsNullOrWhiteSpace($container)) { $container = "super_otonom_vault" }

if (-not (Test-Path $init)) {
    Write-Host "vault_unseal: vault_init.json yok ($init) -- atlandi."
    exit 0
}

# Konteyner ayakta mi? Degilse kisa sure bekle (Docker yeni basladi olabilir).
$running = $null
for ($i = 0; $i -lt 10; $i++) {
    $running = (docker inspect -f "{{.State.Running}}" $container 2>$null)
    if ($running -eq "true") { break }
    Start-Sleep -Seconds 2
}
if ($running -ne "true") {
    Write-Host "vault_unseal: $container calismiyor -- once 'docker compose up -d vault'."
    exit 1
}

# Vault status okunabilene kadar bekle (konteyner var ama Vault hazir olmayabilir).
$st = $null
for ($i = 0; $i -lt 15; $i++) {
    try {
        $stJson = docker exec $container vault status -format=json 2>$null
        if (-not [string]::IsNullOrWhiteSpace($stJson)) {
            $st = $stJson | ConvertFrom-Json
            break
        }
    } catch { }
    Start-Sleep -Seconds 2
}

if ($null -ne $st -and -not $st.sealed) {
    Write-Host "vault_unseal: Vault zaten acik (sealed=false)."
    exit 0
}

# Anahtarlari yukle: once hex, yoksa b64.
$j = Get-Content $init -Raw | ConvertFrom-Json
$keys = $j.unseal_keys_hex
if ($null -eq $keys -or $keys.Count -eq 0) { $keys = $j.unseal_keys_b64 }
if ($null -eq $keys -or $keys.Count -eq 0) {
    Write-Host "vault_unseal: HATA -- vault_init.json icinde unseal_keys_hex/b64 yok."
    exit 1
}

$threshold = [int]$j.unseal_threshold
if ($threshold -lt 1) { $threshold = 1 }
if ($threshold -gt $keys.Count) { $threshold = $keys.Count }

Write-Host "vault_unseal: unseal deneniyor ($threshold/$($keys.Count) share)..."
for ($i = 0; $i -lt $threshold; $i++) {
    docker exec $container vault operator unseal $keys[$i] | Out-Null
}

# Dogrula.
try {
    $finalJson = docker exec $container vault status -format=json 2>$null
    $final = $finalJson | ConvertFrom-Json
    if ($final.sealed) {
        Write-Host "vault_unseal: HATA -- unseal sonrasi hala sealed=true."
        exit 1
    }
} catch {
    Write-Host "vault_unseal: UYARI -- unseal sonrasi status dogrulanamadi."
}

Write-Host "vault_unseal: tamamlandi (sealed=false)."
exit 0
