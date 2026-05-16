# Bant 9 — Dal koruması durum raporu (gh API). Çıktı: konsol + isteğe bağlı docs/BRANCH_PROTECTION_STATUS.md
param(
    [string]$Branch = "main",
    [string]$Repo = "",
    [switch]$WriteDoc
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Get-DefaultRepo {
    $url = (& git remote get-url origin 2>$null)
    if (-not $url) { return "kayi61/super_otonom_v7" }
    if ($url -match 'github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$') {
        return "$($Matches[1])/$($Matches[2])"
    }
    return "kayi61/super_otonom_v7"
}

$expected = @(
    "kanon-drift",
    "ci-quick",
    "go-build",
    "pytest-full",
    "coverage (3.10)",
    "coverage (3.12)",
    "dependency-security"
)

if (-not $Repo) { $Repo = Get-DefaultRepo }
$docPath = Join-Path $root "docs\BRANCH_PROTECTION_STATUS.md"
$verifiedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "HATA: gh kurulu degil."
    exit 1
}

$prevEa = $ErrorActionPreference
$ErrorActionPreference = "Continue"
gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "HATA: gh auth login gerekli."
    exit 1
}
$ErrorActionPreference = $prevEa

$protRaw = gh api "repos/$Repo/branches/$Branch/protection" 2>&1
if ($LASTEXITCODE -ne 0) {
    $msg = ($protRaw | ForEach-Object { $_.ToString() }) -join " "
    Write-Host "Branch protection API basarisiz: $msg"
    Write-Host "  Manuel: .github/REQUIRED_CHECKS.md"
    if ($WriteDoc) {
        $md = @"
# Branch protection durumu — $Repo @ $Branch

**Son doğrulama:** $verifiedAt  
**API sonucu:** **YOK / ERİŞİLEMEDİ** (403 = ücretsiz private repo limiti olabilir)

## Beklenen zorunlu check'ler

$($expected | ForEach-Object { "- ``$_``" } | Out-String)

## Ne yapmalı?

1. `gh auth login` (repo admin)
2. `scripts\setup_branch_protection.ps1` veya Settings → Branches (elle)
3. Ayrıntı: `.github/REQUIRED_CHECKS.md`

"@
        $utf8Bom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($docPath, $md.TrimEnd() + "`n", $utf8Bom)
        Write-Host "Yazildi: $docPath (API basarisiz sablon)"
    }
    exit 1
}

$prot = $protRaw | ConvertFrom-Json
$contexts = @($prot.required_status_checks.contexts | ForEach-Object { "$_" })
$strict = [bool]$prot.required_status_checks.strict
$enforceAdmins = [bool]$prot.enforce_admins.enabled
$reviewCount = [int]$prot.required_pull_request_reviews.required_approving_review_count

$sha = (gh api "repos/$Repo/commits/$Branch" --jq ".sha" 2>$null | Select-Object -First 1).ToString().Trim()
$checkRuns = @()
if ($sha) {
    $cr = gh api "repos/$Repo/commits/$sha/check-runs?per_page=100" 2>$null | ConvertFrom-Json
    if ($cr.check_runs) {
        $checkRuns = @($cr.check_runs | ForEach-Object {
            [PSCustomObject]@{ name = $_.name; conclusion = $_.conclusion }
        })
    }
}

$missing = @($expected | Where-Object { $_ -notin $contexts })
$extra = @($contexts | Where-Object { $_ -notin $expected })
$allExpectedOk = ($missing.Count -eq 0)

Write-Host "=== Branch protection: $Repo @ $Branch ==="
Write-Host "  strict (up to date): $strict"
Write-Host "  enforce_admins: $enforceAdmins"
Write-Host "  PR approving reviews: $reviewCount"
Write-Host "  Zorunlu check sayisi: $($contexts.Count)"
Write-Host "  HEAD: $sha"
if ($missing.Count -gt 0) {
    Write-Host "  EKSIK (beklenen listede yok): $($missing -join ', ')"
}
if ($extra.Count -gt 0) {
    Write-Host "  Ek (beklenen disi): $($extra -join ', ')"
}
if ($allExpectedOk) {
    Write-Host "  [OK] Tum beklenen check'ler zorunlu listede."
}

$checkTable = ""
if ($checkRuns.Count -gt 0) {
    Write-Host ""
    Write-Host "Son commit check-run ozeti:"
    foreach ($r in ($checkRuns | Sort-Object name)) {
        $mark = if ($r.name -in $expected) { "*" } else { " " }
        Write-Host ("  {0} {1,-28} {2}" -f $mark, $r.name, $r.conclusion)
        $reqCol = if ($r.name -in $expected) { "evet" } else { "-" }
        $checkTable += "| ``$($r.name)`` | $($r.conclusion) | $reqCol |`n"
    }
}

$statusLine = if ($allExpectedOk -and $strict -and $enforceAdmins) {
    "**AKTIF** - API ile dogrulandi"
} else {
    "**KISMI** - eksik ayar veya check adi sapmasi"
}

$contextList = ($contexts | ForEach-Object { "- ``$_``" }) -join "`n"
$expectedList = ($expected | ForEach-Object { "- ``$_``" }) -join "`n"
$missingBlock = if ($missing.Count -gt 0) { "`n**Eksik zorunlu check:** $($missing -join ', ')`n" } else { "" }

if ($WriteDoc) {
    $md = @"
# Branch protection durumu - $Repo @ $Branch

**Son dogrulama:** $verifiedAt  
**Durum:** $statusLine  
**HEAD SHA:** ``$sha``

## API ozeti

| Ayar | Deger |
|------|--------|
| Require status checks | evet |
| Require branches up to date (strict) | $strict |
| Enforce admins | $enforceAdmins |
| Required approving reviews | $reviewCount |

## Zorunlu status check'ler (GitHub API)

$contextList

## Beklenen liste (``.github/REQUIRED_CHECKS.md``)

$expectedList
$missingBlock
## Son commit check-run'lari

| Check | Sonuc | Zorunlu listede |
|-------|--------|-----------------|
$checkTable

## Yenileme

``````powershell
scripts\report_branch_protection_status.cmd
``````

Kurulum: ``scripts\fastrun_faz1.cmd`` veya ``scripts\setup_branch_protection.ps1 -Branch main``

403 (ucretsiz private): ``.github/REQUIRED_CHECKS.md`` - elle Settings -> Branches.

"@
    $utf8Bom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($docPath, $md.TrimEnd() + "`n", $utf8Bom)
    Write-Host ""
    Write-Host "Yazildi: $docPath"
}

if (-not $allExpectedOk) { exit 2 }
exit 0
