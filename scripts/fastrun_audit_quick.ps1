# Hizli audit duzeltmeleri: Sharpe TF, main_loop finally, pyproject/Docker uyumu
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_audit_quick: kritik hizli duzeltme dogrulama"

Write-Host ""
Write-Host "=== periods_per_year (1h) ==="
python -c "from super_otonom.data_freshness import periods_per_year_from_timeframe as p; print('1h', p('1h')); print('5m', p('5m'))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_audit_quick_fastrun.py tests/test_sharpe_annualize_fastrun.py tests/test_backtester.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_audit_quick: bitti."
