# Daily backup: critical data/ paths + optional secrets (see docs/DR_BCP.md)
#
# Task Scheduler (elevated CMD example; adjust path):
#   schtasks /Create /TN "SuperOtonom_BackupDaily" /SC DAILY /ST 02:05 /RL LIMITED /F /TR "\"C:\full\path\super_otonom_v7\scripts\backup_daily.cmd\""
# Or: powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1
#
param(
    [string]$BackupRoot = "",
    [int]$RetentionDays = 14,
    [switch]$DryRun,
    [switch]$ExcludeSecrets
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$folderName = Get-Date -Format "yyyyMMdd-HHmmss"
$utcStamp = (Get-Date).ToUniversalTime().ToString("o")
$destParent = if ($BackupRoot) {
    if (-not [IO.Path]::IsPathRooted($BackupRoot)) {
        Join-Path $root $BackupRoot
    } else { $BackupRoot }
} else {
    Join-Path $root "data\backup"
}
$dest = Join-Path $destParent $folderName

$items = @(
    "data\bot_state.json",
    "data\capital_journal.jsonl",
    "data\pending_orders.json",
    "data\orders.jsonl"
)
$dirs = @("data\audit", "data\recon", "data\reports", "data\reconcile")

Write-Host "backup_daily: dest=$dest retention=${RetentionDays}d ExcludeSecrets=$ExcludeSecrets"

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
}

foreach ($rel in $items) {
    $src = Join-Path $root $rel
    if (Test-Path $src) {
        $name = Split-Path $src -Leaf
        if ($DryRun) { Write-Host "  [dry] copy $rel -> $dest\$name" }
        else {
            Copy-Item $src (Join-Path $dest $name) -Force
            Write-Host "  OK $rel"
        }
    }
}

foreach ($rel in $dirs) {
    $src = Join-Path $root $rel
    if (Test-Path $src) {
        $name = Split-Path $rel -Leaf
        if ($DryRun) { Write-Host "  [dry] copydir $rel -> $dest\$name" }
        else {
            Copy-Item $src (Join-Path $dest $name) -Recurse -Force
            Write-Host "  OK $rel/"
        }
    }
}

if (-not $ExcludeSecrets) {
    $secretsDest = Join-Path $dest "secrets"
    $secretFiles = @(
        "data\local\vault_init.json",
        "data\local\vault_admin_token.json",
        "data\local\telegram.env"
    )
    $any = $false
    foreach ($rel in $secretFiles) {
        $src = Join-Path $root $rel
        if (Test-Path $src) {
            $any = $true
            break
        }
    }
    if ($any) {
        if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $secretsDest | Out-Null }
        Write-Host "  (secrets) Backup contains tokens - store encrypted / restrict access."
        foreach ($rel in $secretFiles) {
            $src = Join-Path $root $rel
            if (Test-Path $src) {
                $name = Split-Path $rel -Leaf
                if ($DryRun) { Write-Host "  [dry] copy $rel -> secrets\$name" }
                else {
                    Copy-Item $src (Join-Path $secretsDest $name) -Force
                    Write-Host "  OK secrets\$name"
                }
            }
        }
    }
}

$gitSha = "unknown"
try {
    $gitSha = (& git -C $root rev-parse HEAD 2>$null).Trim()
    if (-not $gitSha) { $gitSha = "unknown" }
} catch { }

$manifest = @(
    "backup_utc=$utcStamp",
    "backup_folder=$folderName",
    "repo_root=$root",
    "git_head=$gitSha",
    "ExcludeSecrets=$ExcludeSecrets",
    "machine=$env:COMPUTERNAME",
    ""
)
if (-not $DryRun) {
    $manifest | Set-Content (Join-Path $dest "BACKUP_MANIFEST.txt") -Encoding utf8
    Write-Host "  OK BACKUP_MANIFEST.txt"
} else {
    Write-Host "  [dry] BACKUP_MANIFEST.txt"
}

if ($RetentionDays -gt 0 -and -not $DryRun) {
    $cut = [datetime]::UtcNow.AddDays(-$RetentionDays)
    Get-ChildItem -LiteralPath $destParent -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.LastWriteTimeUtc -lt $cut) {
            Remove-Item $_.FullName -Recurse -Force
            Write-Host "  prune $($_.Name)"
        }
    }
} elseif ($RetentionDays -gt 0 -and $DryRun) {
    Write-Host "  [dry] retention prune dirs older than $RetentionDays days under $destParent"
}

Write-Host "backup_daily: done."
