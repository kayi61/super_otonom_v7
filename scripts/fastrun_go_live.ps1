# Canli acma oncesi: release_gate + fastrun + deploy_env_check + risk ozeti
# Ayrinti: docs/RUNBOOK.md - Calistirma sozlesmesi
param(
    [switch]$SkipFastrun,
    [switch]$SkipDeployCheck,
    [switch]$SkipRiskSummary
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Invoke-Step([string]$Label, [scriptblock]$Block) {
    Write-Host ""
    Write-Host "=== $Label ==="
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed (exit $LASTEXITCODE)"
    }
}

Write-Host "fastrun_go_live: proje=$root"

Invoke-Step "release_gate (PROMPT-A12)" {
    python -m super_otonom.release_gate
}

if (-not $SkipFastrun) {
    Invoke-Step "pytest fastrun (5000 gate)" {
        python -m pytest -m fastrun -q --tb=short
    }
}

Invoke-Step "ortam ozeti (sir gosterilmez)" {
    python scripts/go_live_env_summary.py
}

if (-not $SkipDeployCheck) {
    Invoke-Step "deploy_env_check" {
        python -m super_otonom.deploy_env_check
    }
}

if (-not $SkipRiskSummary) {
    $riskScript = Join-Path $root "scripts\print_resolved_risk.py"
    if (Test-Path $riskScript) {
        Invoke-Step "print_resolved_risk --summary" {
            python $riskScript --summary
        }
    } else {
        Write-Host "UYARI: print_resolved_risk.py yok - atlandi."
    }
}

Write-Host ""
Write-Host "fastrun_go_live: bitti."
Write-Host "  Sonraki: docs/RUNBOOK.md - Canli acma sirasi"
Write-Host "  Bot (sim):  python -m super_otonom.main_loop"
Write-Host "  Canli:      DRY_RUN=false PAPER_MODE=false LIVE_CONFIRM=YES + Vault, sonra main_loop"
