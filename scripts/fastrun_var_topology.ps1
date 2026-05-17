# Audit 11: VaR/CVaR faz-24 vs canli tick disclosure
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_var_topology: VaR topolojisi (phase24 vs live tick)"

python -m super_otonom.var_topology_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
python -c "import json; from super_otonom.var_topology import var_disclosure; print(json.dumps(var_disclosure(), indent=2, ensure_ascii=False))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_var_topology_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_var_topology: bitti."
