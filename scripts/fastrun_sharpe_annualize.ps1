# Audit 1: Sharpe annualize — kripto 7/24, TF uyumu, edge_evidence metadata
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_sharpe_annualize: TF bazli periods_per_year dogrulama"

Write-Host ""
Write-Host "=== sharpe_audit (repo tarama) ==="
python -m super_otonom.sharpe_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== periods_per_year tablosu ==="
python -c @"
from super_otonom.data_freshness import (
    LEGACY_PERIODS_PER_YEAR_STOCK_5M as leg,
    periods_per_year_from_timeframe as p,
    sharpe_annualize_factor_vs_legacy as f,
)
for tf in ('5m', '15m', '1h', '4h'):
    print(f'{tf:4} ppy={p(tf):.1f}  Sharpe/legacy={f(tf):.4f}')
print(f'legacy (yanlis sabit) = {leg:.1f}')
"@

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_sharpe_annualize_fastrun.py tests/test_audit_quick_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "=== edge_evidence (synthetic 5m, json metadata) ==="
$env:DRY_RUN = "1"
$prevEa = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -c @"
import io, json
from contextlib import redirect_stdout
from super_otonom.edge_evidence import main
buf = io.StringIO()
with redirect_stdout(buf):
    code = main(['--source','synthetic','--timeframe','5m','--limit','220','--no-wfa','--json'])
assert code == 0, code
d = json.loads(buf.getvalue())
assert d['timeframe'] == '5m' and d['periods_per_year'] > 100_000
print('edge_evidence OK', d['timeframe'], d['periods_per_year'])
"@ 2>$null | Out-Null
$edgeEc = $LASTEXITCODE
$ErrorActionPreference = $prevEa
if ($edgeEc -ne 0) { exit $edgeEc }
Write-Host "edge_evidence OK (5m, ppy~105192)"

Write-Host ""
Write-Host "fastrun_sharpe_annualize: bitti."
