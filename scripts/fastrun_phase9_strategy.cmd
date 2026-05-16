@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_phase9_strategy.ps1" %*
exit /b %ERRORLEVEL%
