# Audit 7: god package / düz modül topolojisi + manifest + iddia taramasi
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_package_topology: düz modül envanteri + manifest"

python -m super_otonom.package_topology_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
python -c "import json; from super_otonom.package_topology import package_disclosure; print(json.dumps(package_disclosure(), indent=2, ensure_ascii=False))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_package_topology_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_package_topology: bitti."
