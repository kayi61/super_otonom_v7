@echo off
cd /d "%~dp0.."
echo === DNS / Binance erisim testi ===
nslookup api.binance.com
nslookup stream.binance.com
echo.
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'https://api.binance.com/api/v3/ping' -UseBasicParsing -TimeoutSec 10).Content } catch { Write-Host 'HATA:' $_.Exception.Message }"
echo.
echo DNS veya ping basarisizsa bot Binance verisi cekemez (Vault ayri konu).
pause
