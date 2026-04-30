@echo off
echo ================================
echo   J.A.R.V.I.S. Telegram Bot
echo ================================
echo.

REM Gerekli paketleri yükle
echo Paketler kontrol ediliyor...
pip install python-telegram-bot openai-whisper gtts ffmpeg-python anthropic openai -q

REM Token kontrolü
if "%TELEGRAM_TOKEN%"=="" (
    set /p TELEGRAM_TOKEN="Telegram Bot Token girin (BotFather'dan): "
)

if "%ANTHROPIC_API_KEY%"=="" (
    set /p ANTHROPIC_API_KEY="Anthropic API Key girin (Claude icin): "
)

if "%JARVIS_USER_ID%"=="" (
    set /p JARVIS_USER_ID="Telegram Kullanici ID'niz (bos birakabilirsiniz): "
)

echo.
echo Bot baslatiliyor...
echo LM Studio acik olmali ve sunucu calisıyor olmali!
echo.
python telegram_bot.py
pause
