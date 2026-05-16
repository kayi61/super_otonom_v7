@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_audit_quick.ps1" %*
exit /b %ERRORLEVEL%
