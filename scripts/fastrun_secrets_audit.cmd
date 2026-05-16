@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_secrets_audit.ps1" %*
exit /b %ERRORLEVEL%
