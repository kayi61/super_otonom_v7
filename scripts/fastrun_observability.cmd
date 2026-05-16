@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_observability.ps1" %*
exit /b %ERRORLEVEL%
