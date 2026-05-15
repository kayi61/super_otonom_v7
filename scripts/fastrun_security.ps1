# Bagimlilik guvenligi fastrun: pip-audit + SBOM + CVE SLA
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "[1/2] pip-audit kurulumu..."
python -m pip install --upgrade pip pip-audit>=2.7.0 -q

Write-Host "[2/2] tarama + SBOM + SLA..."
python scripts/dependency_security.py --sbom --fail-on critical,high
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "fastrun_security: CVE bulundu (critical/high). artifacts/cve-report.json"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "fastrun_security: bitti."
Write-Host "  SBOM: artifacts\sbom.cyclonedx.json"
Write-Host "  Rapor: artifacts\cve-report.json"
