@echo off
setlocal
cd /d "%~dp0.."
python -m super_otonom.universe_schedule_fetch --top-n 8 --include-delist
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
echo.
echo Schedule: data\universe_schedule_binance.json
echo Meta:    data\universe_schedule_binance.meta.json
exit /b %ERRORLEVEL%
