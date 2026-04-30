@echo off
echo ================================
echo   J.A.R.V.I.S. Web Sunucusu
echo ================================
echo.

pip install flask -q

if "%ANTHROPIC_API_KEY%"=="" (
    set /p ANTHROPIC_API_KEY="Anthropic API Key (bos birakabilirsin): "
)

echo.
echo Web sunucusu baslatiliyor...
echo Telefon icin ayni Wi-Fi'de olun!
echo.
py jarvis_web.py
pause
