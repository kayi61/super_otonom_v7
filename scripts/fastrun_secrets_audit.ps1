# PROMPT 2 — Sir denetimi (Vault-only / .env / deploy_env_check)
param(
    [switch]$SkipPytest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_secrets_audit: PROMPT 2 (sirlar dokumana yazilmaz)"
python -m super_otonom.secrets_audit
$code = $LASTEXITCODE
if ($code -ne 0 -and $code -ne 2) {
    Write-Host "secrets_audit FAIL (exit $code) — docs\SECRETS_AUDIT_LAST.md"
    exit $code
}
if ($code -eq 2) {
    Write-Host "secrets_audit WARN (exit 2) — canli oncesi inceleyin"
}

if (-not $SkipPytest) {
    Write-Host ""
    python -m pytest tests/test_secrets_audit_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_secrets_audit: bitti."
exit 0
