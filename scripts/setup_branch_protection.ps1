# GitHub branch protection: ci-quick + pytest-full (+ coverage, kanon-drift)
# Gerekli: $env:GITHUB_TOKEN (repo admin) veya gh auth login
# Kullanim: powershell -File scripts/setup_branch_protection.ps1 [-Branch main]

param(
    [string]$Branch = "main",
    [string]$Repo = "kayi61/super_otonom_v7"
)

$ErrorActionPreference = "Stop"
$checks = @("kanon-drift", "ci-quick", "pytest-full", "coverage")

function Set-Protection-Gh {
    param([string]$OwnerRepo, [string]$BranchName, [string[]]$Contexts)
    $ctx = $Contexts -join ","
    gh api -X PUT "repos/$OwnerRepo/branches/$BranchName/protection" -f required_status_checks[strict]=true `
        -f required_status_checks[contexts][]=@Contexts 2>&1
}

function Set-Protection-Api {
    param([string]$OwnerRepo, [string]$BranchName, [string[]]$Contexts, [string]$Token)
    $parts = $OwnerRepo.Split("/")
    $body = @{
        required_status_checks = @{
            strict   = $true
            contexts = $Contexts
        }
        enforce_admins                  = $false
        required_pull_request_reviews   = @{
            required_approving_review_count = 0
        }
        restrictions = $null
    } | ConvertTo-Json -Depth 5
    $uri = "https://api.github.com/repos/$OwnerRepo/branches/$([uri]::EscapeDataString($BranchName))/protection"
    $headers = @{
        Authorization = "Bearer $Token"
        Accept        = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    Invoke-RestMethod -Method Put -Uri $uri -Headers $headers -Body $body -ContentType "application/json"
}

Write-Host "Hedef: $Repo @ $Branch"
Write-Host "Zorunlu check'ler: $($checks -join ', ')"

if (Get-Command gh -ErrorAction SilentlyContinue) {
    $json = @{
        required_status_checks        = @{ strict = $true; contexts = $checks }
        enforce_admins                = $false
        required_pull_request_reviews = @{ required_approving_review_count = 0 }
        restrictions                  = $null
    } | ConvertTo-Json -Depth 5 -Compress
    $json | gh api -X PUT "repos/$Repo/branches/$Branch/protection" --input -
    Write-Host "OK: branch protection (gh)"
    exit 0
}

$token = $env:GITHUB_TOKEN
if ($token) {
    Set-Protection-Api -OwnerRepo $Repo -BranchName $Branch -Contexts $checks -Token $token
    Write-Host "OK: branch protection (API)"
    exit 0
}

Write-Host ""
Write-Host "MANUEL (GitHub web):"
Write-Host "  Repo -> Settings -> Branches -> $Branch -> Add rule"
Write-Host "  [x] Require status checks before merging"
Write-Host "  [x] Require branches to be up to date"
Write-Host "  Status checks (hepsini secin):"
foreach ($c in $checks) { Write-Host "    - $c" }
Write-Host ""
Write-Host "Not: CI workflow push edildikten sonra check isimleri listede gorunur."
exit 1
