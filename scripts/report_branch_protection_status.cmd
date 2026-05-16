@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0report_branch_protection_status.ps1" -WriteDoc %*
exit /b %ERRORLEVEL%
