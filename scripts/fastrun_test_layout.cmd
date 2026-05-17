@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fastrun_test_layout.ps1" %*
exit /b %ERRORLEVEL%
