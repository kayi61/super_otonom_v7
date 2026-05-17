# Audit 5: tek-host HA — topoloji dogrulama + repo iddia taramasi
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_ha: tek-host topoloji + HA iddia taramasi"

python -m super_otonom.ha_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
python -c "import json; from super_otonom.ha_topology import ha_disclosure; print(json.dumps(ha_disclosure(), indent=2, ensure_ascii=False))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_ha_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_ha: bitti."
