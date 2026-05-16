# Faz 9 — Strateji / ticari gerçekçilik: edge kanıtı + küçük canlı runbook referansı
param(
    [switch]$SkipPytest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_phase9_strategy: Faz 9.1 edge_evidence (synthetic, hızlı)"
python -m super_otonom.edge_evidence --source synthetic --timeframe 5m --symbols BTC/USDT,ETH/USDT --limit 400 --fee-bps 10 --slip-min 0.0002 --slip-max 0.0012 --exec-seed 42
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "pytest tests/test_edge_evidence_fastrun.py"
    python -m pytest tests/test_edge_evidence_fastrun.py tests/test_sharpe_annualize_fastrun.py tests/test_survivorship_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "Faz 9.2 canlı küçük nominal: docs/RUNBOOK.md — 'Faz 9'"
Write-Host "Tamam."
