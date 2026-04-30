#!/bin/bash
# J.A.R.V.I.S. — Web + Telegram birlikte başlat

cd "$(dirname "$0")"

# .env dosyasını yükle
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo "✓ .env yüklendi"
fi

source ~/.bashrc 2>/dev/null

echo "╔══════════════════════════════════════╗"
echo "║   J.A.R.V.I.S. Başlatılıyor         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Web sunucusunu arka planda başlat
echo "→ Web sunucusu başlatılıyor..."
python3 jarvis_web.py &
WEB_PID=$!
echo "   PID: $WEB_PID"

sleep 2

# Telegram botu başlat (eğer token varsa)
if [ -n "$TELEGRAM_TOKEN" ]; then
    echo "→ Telegram botu başlatılıyor..."
    python3 telegram_bot.py &
    TG_PID=$!
    echo "   PID: $TG_PID"
else
    echo "   Telegram token yok, bot atlandı."
    TG_PID=""
fi

echo ""
echo "✅ Sistemler hazır!"
echo "   Web:      http://localhost:5000"
echo "   Durdurmak için Ctrl+C"
echo ""

# Her ikisi de kapatılınca temizle
cleanup(){
    echo "Kapatılıyor..."
    kill $WEB_PID 2>/dev/null
    [ -n "$TG_PID" ] && kill $TG_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

wait
