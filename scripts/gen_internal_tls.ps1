# Self-signed TLS (dev / ic ag) — docker/tls/cert.pem + key.pem
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tlsDir = Join-Path $root "docker\tls"
New-Item -ItemType Directory -Path $tlsDir -Force | Out-Null
$cert = Join-Path $tlsDir "cert.pem"
$key = Join-Path $tlsDir "key.pem"
if (Get-Command openssl -ErrorAction SilentlyContinue) {
    openssl req -x509 -nodes -days 825 -newkey rsa:2048 `
        -keyout $key -out $cert `
        -subj "/CN=super-otonom-local/O=SuperOtonomDev"
    Write-Host "gen_internal_tls: OK ($cert)"
} else {
    Write-Host "gen_internal_tls: openssl yok — TLS icin Git Bash veya OpenSSL kurun."
    exit 1
}
