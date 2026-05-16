# Audit 2: hard_safety_contract — enforcement map + RISK wiring (sahte degil: denetlenebilir)
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_hard_safety: hard_safety_contract enforce + wiring audit"

Write-Host ""
Write-Host "=== audit CLI ==="
$env:DRY_RUN = "1"
$prevEa = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m super_otonom.hard_safety_contract 2>$null
$auditEc = $LASTEXITCODE
$ErrorActionPreference = $prevEa
if ($auditEc -ne 0) { exit $auditEc }

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_hard_safety_contract_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_hard_safety: bitti."
