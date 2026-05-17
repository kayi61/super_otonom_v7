# Audit 8: BotEngine god-class LOC + manifest + iddia taramasi
param([switch]$SkipPytest)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "fastrun_bot_engine_topology: BotEngine LOC + god-class disclosure"

python -m super_otonom.bot_engine_audit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
python -c "import json; from super_otonom.bot_engine_topology import bot_engine_disclosure; print(json.dumps(bot_engine_disclosure(), indent=2, ensure_ascii=False))"

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "=== pytest ==="
    python -m pytest tests/test_bot_engine_topology_fastrun.py -q --tb=short
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "fastrun_bot_engine_topology: bitti."
