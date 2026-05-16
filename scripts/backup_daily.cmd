@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_daily.ps1" %*
exit /b %ERRORLEVEL%
