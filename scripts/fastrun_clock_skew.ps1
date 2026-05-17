# Audit 6: clock skew metrik/alarmlari + repo iddia taramasi
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_clock_skew: borsa skew + NTP disclosure"

python -m super_otonom.clock_skew_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
python -c "import json; from super_otonom.clock_skew import sample_disclosure_payload; print(json.dumps(sample_disclosure_payload(), indent=2, ensure_ascii=False))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_clock_skew_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_clock_skew: bitti."
