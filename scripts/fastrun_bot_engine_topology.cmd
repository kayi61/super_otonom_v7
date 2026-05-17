@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_bot_engine_topology.ps1" %*
exit /b %ERRORLEVEL%
