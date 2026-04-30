@echo off
echo ================================
echo   J.A.R.V.I.S. Kurulum Basliyor
echo ================================
echo.

REM API anahtarını kontrol et
if "%ANTHROPIC_API_KEY%"=="" (
    echo UYARI: ANTHROPIC_API_KEY bulunamadi!
    echo.
    set /p API_KEY="Anthropic API anahtarinizi girin: "
    set ANTHROPIC_API_KEY=%API_KEY%
)

REM Gerekli paketleri yükle
echo Gerekli paketler yukleniyor...
pip install anthropic SpeechRecognition pyttsx3 pyaudio

echo.
echo ================================
echo   J.A.R.V.I.S. Baslatiliyor...
echo ================================
python jarvis.py
pause
