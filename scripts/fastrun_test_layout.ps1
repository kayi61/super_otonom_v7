# Audit 9: paket ici test_*.py envanteri + wheel exclude dogrulama
param([switch]$SkipPytest, [switch]$SkipWheel)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_test_layout: in-package test modulleri + wheel exclude"

$wheelArg = @()
if (-not $SkipWheel) { $wheelArg = @("--verify-wheel") }

python -m super_otonom.layout_topology_audit @wheelArg
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
python -c "import json; from super_otonom.layout_topology import layout_disclosure; print(json.dumps(layout_disclosure(), indent=2, ensure_ascii=False))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_test_layout_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_test_layout: bitti."
