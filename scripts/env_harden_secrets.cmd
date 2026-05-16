@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0env_harden_secrets.ps1" %*
exit /b %ERRORLEVEL%
