# Audit 4: survivorship bias — disclosure, cok sembol, repo tarama
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_survivorship: survivorship disclosure + evren backtest"

Write-Host ""
Write-Host "=== survivorship_audit ==="
python -m super_otonom.survivorship_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$sched = Join-Path $root "data\universe_schedule_binance.json"
if (Test-Path $sched) {
    Write-Host ""
    Write-Host "=== universe schedule (disk) ==="
    python -c "import json; d=json.load(open(r'$sched',encoding='utf-8')); print(len(d), 'symbols'); print([x['symbol'] for x in d[:5]], '...')"
}

Write-Host ""
Write-Host "=== edge_evidence (schedule + 4 sembol, synthetic) ==="
$env:DRY_RUN = "1"
$prevEa = $ErrorActionPreference
$ErrorActionPreference = "Continue"
if (Test-Path $sched) {
    python -m super_otonom.edge_evidence --source synthetic --symbols BTC/USDT,ETH/USDT,OCEAN/USDT,WAVES/USDT --universe-schedule data/universe_schedule_binance.json --timeframe 5m --limit 120 --no-wfa 2>$null | Out-Null
} else {
    python -m super_otonom.edge_evidence --source synthetic --symbols BTC/USDT,ETH/USDT --timeframe 5m --limit 150 --no-wfa 2>$null | Out-Null
}
$ec = $LASTEXITCODE
$ErrorActionPreference = $prevEa
if ($ec -ne 0) { exit $ec }
Write-Host "edge_evidence multi-symbol OK"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_survivorship_fastrun.py tests/test_edge_evidence_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_survivorship: bitti."
