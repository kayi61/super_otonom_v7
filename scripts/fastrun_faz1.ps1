# Faz 1: GitHub branch protection + Dependabot durumu (gh + repo admin)
# Oncelik: gh auth login   Sonra: scripts\fastrun_faz1.cmd
param(
    [string]$Branch = "main",
    [string]$Repo = "",
    [switch]$SkipBranchProtection,
    [switch]$SkipDependabotList
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

if (-not $Repo) { $Repo = Get-DefaultRepo }

Write-Host "fastrun_faz1: Faz 1 (branch protection + Dependabot)"
Write-Host "  Repo=$Repo Branch=$Branch"
Write-Host ""

if (-not (Test-Path ".github\dependabot.yml")) {
    Write-Host "UYARI: .github\dependabot.yml yok"
} else {
    Write-Host "[OK] .github\dependabot.yml mevcut (pip + github-actions + docker)"
}

Write-Host ""

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "HATA: GitHub CLI (gh) kurulu degil."
    Write-Host "  https://cli.github.com/  Sonra: gh auth login"
    exit 1
}

$prevEa = $ErrorActionPreference
$ErrorActionPreference = "Continue"
gh auth status *> $null
$ghAuthOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEa

if (-not $ghAuthOk) {
    Write-Host "HATA: gh ile giris yok."
    Write-Host "  Calistir: gh auth login"
    Write-Host "  (Repo admin yetkisi + workflow izni gerekir)"
    Write-Host ""
    Write-Host "Manuel: https://github.com/$Repo/settings/branches"
    exit 1
}

if (-not $SkipBranchProtection) {
    Write-Host "=== Branch protection API ==="
    # Ayri powershell.exe: setup_branch_protection.ps1 icindeki exit ust script'i oldurmesin; ExitCode guvenilir olsun.
    # Bosluklu yollar: ArgumentList dizi ile -File yolu ikiye bolunuyordu; tek komut satiri + ic tirnak.
    $bpPs = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $bpPs)) { $bpPs = "powershell.exe" }
    $bpFile = Join-Path $root "scripts\setup_branch_protection.ps1"
    $bpArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$bpFile`" -Branch `"$Branch`" -Repo `"$Repo`""
    $bpProc = Start-Process -FilePath $bpPs -ArgumentList $bpArgs -Wait -PassThru -NoNewWindow
    $bpExit = 1
    if ($null -ne $bpProc.ExitCode) { $bpExit = $bpProc.ExitCode }
    if ($bpExit -ne 0) {
        Write-Host "Branch protection basarisiz (exit $bpExit). Manuel: .github/REQUIRED_CHECKS.md"
        exit $bpExit
    }
}

if (-not $SkipDependabotList) {
    Write-Host ""
    Write-Host "=== Acik Dependabot PR (ilk 15) ==="
    gh pr list --repo $Repo --author app/dependabot --limit 15 2>&1
}

Write-Host ""
Write-Host "fastrun_faz1: bitti."
