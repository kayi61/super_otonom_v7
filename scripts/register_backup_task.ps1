# Daily backup: register Windows Task Scheduler (/TR max 261 chars — use backup_daily.cmd wrapper)
param(
    [string]$TaskName = "SuperOtonom_BackupDaily",
    [string]$StartTime = "02:05",
    [string]$BackupRoot = "",
    [switch]$ExcludeSecrets
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$batPath = Join-Path $root "scripts\backup_daily.cmd"
if (-not (Test-Path $batPath)) { throw "backup_daily.cmd not found: $batPath" }

$tr = '"' + $batPath + '"'
if ($ExcludeSecrets) {
    $tr += " -ExcludeSecrets"
}
if ($BackupRoot) {
    $tr += ' -BackupRoot "' + $BackupRoot.Replace('"', '\"') + '"'
}

if ($tr.Length -gt 261) {
    throw "schtasks /TR limit 261 chars; current=$($tr.Length). Shorten BackupRoot or register manually via Task Scheduler GUI."
}

& schtasks.exe /Create /TN $TaskName /SC DAILY /ST $StartTime /RL LIMITED /F /TR $tr
if ($LASTEXITCODE -ne 0) {
    throw "schtasks failed (try elevated PowerShell / Administrator): exit=$LASTEXITCODE"
}
Write-Host "register_backup_task: OK TaskName=$TaskName daily $StartTime TR_len=$($tr.Length)"
