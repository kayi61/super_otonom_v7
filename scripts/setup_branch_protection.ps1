# GitHub branch protection: status checks + solo PR (0 onay)
# gh auth login veya GITHUB_TOKEN (repo admin). Varsayilan: son basarili commit'teki check isimlerini keşfeder.
#
# Kullanim:
#   scripts\setup_branch_protection.ps1 [-Branch main] [-Repo owner/repo] [-ApprovingReviews 0]
#   scripts\setup_branch_protection.ps1 -NoDiscover   # sabit liste (coverage matrix sablon)

param(
    [string]$Branch = "main",
    [string]$Repo = "",
    [int]$ApprovingReviews = 0,
    [switch]$NoDiscover
)

$ErrorActionPreference = "Stop"

function Get-DefaultRepo {
    $url = (& git remote get-url origin 2>$null)
    if (-not $url) { return "kayi61/super_otonom_v7" }
    if ($url -match 'github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$') {
        return "$($Matches[1])/$($Matches[2])"
    }
    return "kayi61/super_otonom_v7"
}

function Invoke-GhJson {
    param([Parameter(Mandatory)][string[]]$GhArguments)
    $prevEa = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $out = & gh @GhArguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEa
    return @{ Out = $out; Code = $code }
}

function Get-DiscoveredCheckContexts {
    param([string]$OwnerRepo, [string]$BranchName)
    $r = Invoke-GhJson -GhArguments @("api", "repos/$OwnerRepo/commits/$BranchName", "--jq=.sha")
    if ($r.Code -ne 0 -or -not $r.Out) {
        Write-Host "Discover: commit SHA alinamadi - sablon context listesi kullanilacak."
        return @()
    }
    $sha = ($r.Out | Select-Object -First 1).ToString().Trim()
    if (-not $sha) { return @() }
    $r2 = Invoke-GhJson -GhArguments @("api", "repos/$OwnerRepo/commits/$sha/check-runs?per_page=100")
    if ($r2.Code -ne 0) {
        Write-Host "Discover: check-runs alinamadi - sablon kullanilacak."
        $hint = @($r2.Out | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ }) | Select-Object -First 3
        if ($hint.Count -gt 0) {
            Write-Host ("  gh ciktisi: " + ($hint -join " | "))
        }
        return @()
    }
    $rawJson = ($r2.Out | ForEach-Object { $_.ToString() }) -join ""
    if (-not $rawJson.Trim()) {
        Write-Host "Discover: check-runs bos - sablon kullanilacak."
        return @()
    }
    try {
        $doc = $rawJson | ConvertFrom-Json
    }
    catch {
        Write-Host "Discover: check-runs JSON parse edilemedi - sablon kullanilacak."
        Write-Host ("  Parse hatasi: " + $_.Exception.Message)
        return @()
    }
    if (-not $doc.check_runs) {
        Write-Host "Discover: check_runs alani yok - sablon kullanilacak."
        return @()
    }
    $runs = @($doc.check_runs)
    $raw = @(
        $runs |
        Where-Object { $_.conclusion -eq "success" -and $_.name } |
        ForEach-Object { $_.name.ToString().Trim() } |
        Where-Object { $_ }
    )
    $uniq = $raw | Sort-Object -Unique
    $short = if ($sha.Length -ge 7) { $sha.Substring(0, 7) } else { $sha }
    Write-Host "Discover: $($uniq.Count) basarili check adi bulundu (HEAD $short)..."
    return @($uniq)
}

function Build-Contexts {
    param(
        [string[]]$Discovered,
        [switch]$ForceTemplate
    )
    $mandatory = @(
        "kanon-drift",
        "ci-quick",
        "go-build",
        "pytest-full",
        "dependency-security"
    )
    $templateCoverage = @("coverage (3.10)", "coverage (3.12)")

    if ($ForceTemplate -or $Discovered.Count -eq 0) {
        Write-Host "Context listesi: sablon (matrix + dependency-security)."
        return @($mandatory + $templateCoverage | Sort-Object -Unique)
    }

    $fromCi = @() + $mandatory
    foreach ($m in $mandatory) {
        $hit = $Discovered | Where-Object { $_ -eq $m }
        if (-not $hit) {
            Write-Host "UYARI: '$m' son committe basarili check-run'da gorunmedi - yine de zorunlu liste."
        }
    }

    $cov = @($Discovered | Where-Object { $_ -match '(?i)^coverage' })
    if ($cov.Count -ge 2) {
        Write-Host "Coverage checks (discover): $($cov -join ', ')"
        $merged = $fromCi + $cov
    } elseif ($cov.Count -eq 1) {
        Write-Host "Coverage checks (discover): $($cov[0])"
        $merged = $fromCi + $cov
    } else {
        Write-Host "Coverage: matrix sablon coverage (3.10)/(3.12) ekleniyor."
        $merged = $fromCi + $templateCoverage
    }

    return @($merged | Sort-Object -Unique)
}

function Invoke-PutProtection {
    param(
        [string]$OwnerRepo,
        [string]$BranchName,
        [string[]]$Contexts,
        [int]$Approvals
    )
    $payload = @{
        required_status_checks        = @{ strict = $true; contexts = @($Contexts) }
        enforce_admins                = $true
        required_pull_request_reviews = @{
            dismiss_stale_reviews           = $false
            require_code_owner_reviews       = $false
            required_approving_review_count  = $Approvals
        }
        restrictions                  = $null
    } | ConvertTo-Json -Depth 8 -Compress

    # stdin pipe + PS 5.1: LASTEXITCODE bozulabiliyor; gecici dosya ile gh sonucu net.
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("gh-branch-protection-{0}.json" -f [Guid]::NewGuid().ToString('n'))
    try {
        [System.IO.File]::WriteAllText($tmp, $payload, [System.Text.UTF8Encoding]::new($false))
        $prevEa = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $ghMsg = & gh api -X PUT "repos/$OwnerRepo/branches/$BranchName/protection" --input $tmp 2>&1
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEa
        if ($code -ne 0) {
            $txt = ($ghMsg | ForEach-Object { $_.ToString() }) -join " "
            if ($txt -match 'Upgrade to GitHub Pro|403') {
                Write-Host ""
                Write-Host "GitHub limiti (403): Ucretsiz PRIVATE repoda klasik Branch Protection API kapali."
                Write-Host "  Cozum secenekleri: repo PUBLIC yap, GitHub Pro / Team+, veya kurumsal Rulesets."
                Write-Host "  Elle kontrol listesi: .github/REQUIRED_CHECKS.md"
                Write-Host ""
                $script:GhBranchProtectionPlanBlocked = $true
            }
            elseif ($txt.Trim()) {
                Write-Host "gh API: $txt"
            }
        }
        return $code
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

if (-not $Repo) { $Repo = Get-DefaultRepo }

Write-Host "Hedef: $Repo @ $Branch | Solo onay sayisi: $ApprovingReviews"

$discovered = @()
if (-not $NoDiscover) {
    $prevEa = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    gh auth status *> $null
    $ghOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prevEa
    if ($ghOk) {
        $discovered = @(Get-DiscoveredCheckContexts -OwnerRepo $Repo -BranchName $Branch)
    }
}

$checks = @((Build-Contexts -Discovered $discovered) | ForEach-Object { $_ })
$checks = @($checks | ForEach-Object { "$_" } | Where-Object { $_ })
Write-Host "Zorunlu check'ler ($($checks.Count)): $($checks -join ', ')"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "gh yok."
    exit 1
}

$prevEa = $ErrorActionPreference
$ErrorActionPreference = "Continue"
gh auth status *> $null
$ghOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEa

if (-not $ghOk) {
    Write-Host "gh auth login gerekli."
    exit 1
}

$script:GhBranchProtectionPlanBlocked = $false
$exitPut = Invoke-PutProtection -OwnerRepo $Repo -BranchName $Branch -Contexts $checks -Approvals $ApprovingReviews
if ($exitPut -eq 0) {
    Write-Host "OK: branch protection (gh) - dependency-security + coverage + PR reviews count=$ApprovingReviews"
    exit 0
}

if ($script:GhBranchProtectionPlanBlocked) {
    Write-Host "Plan limiti nedeniyle ikinci PUT denemesi atlandi."
    exit 1
}

Write-Host "Ilk PUT basarisiz (exit $exitPut) - tek 'coverage' ile yeniden deneniyor..."
$checks2 = @((Build-Contexts -Discovered $discovered -ForceTemplate) | ForEach-Object { $_ })
$checks2 = ($checks2 | Where-Object { $_ -notmatch '^coverage \(' }) + @("coverage") | Sort-Object -Unique
$exitPut2 = Invoke-PutProtection -OwnerRepo $Repo -BranchName $Branch -Contexts $checks2 -Approvals $ApprovingReviews
if ($exitPut2 -eq 0) {
    Write-Host "OK: branch protection (alternatif coverage tek ad)"
    exit 0
}

Write-Host "HATA: branch protection API (exit $exitPut2). GitHub arayuzunden check adlarini dogrula."
Write-Host ('  Son commit: gh api repos/{0}/commits/{1}/check-runs --jq ''.check_runs[].name''' -f $Repo, $Branch)
exit 1
