# Gunluk yedek — data/ kritik dosyalar (DR_BCP)
param(
    [string]$BackupRoot = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$date = Get-Date -Format "yyyyMMdd"
$dest = if ($BackupRoot) { Join-Path $BackupRoot $date } else { Join-Path $root "data\backup\$date" }

$items = @(
    "data\bot_state.json",
    "data\capital_journal.jsonl",
    "data\pending_orders.json",
    "data\orders.jsonl"
)
$dirs = @("data\audit", "data\recon", "data\reports")

Write-Host "backup_daily: hedef=$dest"
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $dest | Out-Null }

foreach ($rel in $items) {
    $src = Join-Path $root $rel
    if (Test-Path $src) {
        $name = Split-Path $src -Leaf
        if ($DryRun) { Write-Host "  [dry] copy $rel -> $dest\$name" }
        else { Copy-Item $src (Join-Path $dest $name) -Force; Write-Host "  OK $rel" }
    }
}

foreach ($rel in $dirs) {
    $src = Join-Path $root $rel
    if (Test-Path $src) {
        $name = Split-Path $rel -Leaf
        if ($DryRun) { Write-Host "  [dry] copydir $rel -> $dest\$name" }
        else { Copy-Item $src (Join-Path $dest $name) -Recurse -Force; Write-Host "  OK $rel/" }
    }
}

Write-Host "backup_daily: bitti."
