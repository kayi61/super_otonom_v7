@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_sharpe_annualize.ps1" %*
exit /b %ERRORLEVEL%
