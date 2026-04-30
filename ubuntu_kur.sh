#!/bin/bash
# ═══════════════════════════════════════════════════
#   J.A.R.V.I.S. Ubuntu Kurulum Scripti
#   Tailscale üzerinden Windows LM Studio bağlantısı
# ═══════════════════════════════════════════════════

set -e
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   J.A.R.V.I.S. Ubuntu Kurulumu      ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Python paketleri ──────────────────────────────────────────────────────────
echo "→ Python paketleri kuruluyor..."
pip3 install anthropic openai flask flask-socketio python-socketio \
    werkzeug requests schedule python-telegram-bot \
    pyttsx3 speechrecognition sounddevice pypdf \
    pywebpush cryptography gtts openai-whisper \
    --break-system-packages 2>/dev/null || \
pip3 install anthropic openai flask flask-socketio python-socketio \
    werkzeug requests schedule python-telegram-bot \
    pyttsx3 speechrecognition sounddevice pypdf \
    pywebpush cryptography gtts openai-whisper

# ── Ses desteği (Ubuntu) ──────────────────────────────────────────────────────
echo "→ Ses kütüphaneleri kuruluyor..."
sudo apt-get install -y python3-pyaudio portaudio19-dev espeak espeak-data libespeak1 ffmpeg 2>/dev/null || true

# ── Tailscale LM Studio URL ayarı ─────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Windows PC'nin Tailscale IP'sini girin         ║"
echo "║   (Windows'ta: tailscale ip -4)                  ║"
echo "║   Boş bırakırsanız localhost kullanılır          ║"
echo "╚══════════════════════════════════════════════════╝"
read -p "Tailscale IP [örn: 100.64.0.5]: " TS_IP

if [ -n "$TS_IP" ]; then
    LM_URL="http://${TS_IP}:1234/v1"
    echo "export LM_STUDIO_URL=\"${LM_URL}\"" >> ~/.bashrc
    export LM_STUDIO_URL="${LM_URL}"
    echo "✓ LM Studio URL: ${LM_URL}"
else
    echo "✓ localhost kullanılacak"
fi

# ── Anthropic API Key ──────────────────────────────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ]; then
    read -p "Anthropic API Key (Claude için, boş bırakılabilir): " API_KEY
    if [ -n "$API_KEY" ]; then
        echo "export ANTHROPIC_API_KEY=\"${API_KEY}\"" >> ~/.bashrc
        export ANTHROPIC_API_KEY="${API_KEY}"
        echo "✓ API key kaydedildi"
    fi
fi

# ── Başlatma scripti ──────────────────────────────────────────────────────────
cat > ~/jarvis_baslat.sh << 'SCRIPT'
#!/bin/bash
source ~/.bashrc
cd "$(dirname "$0")"
echo "J.A.R.V.I.S. başlatılıyor..."
echo "Web: http://localhost:5000"
python3 jarvis_web.py
SCRIPT
chmod +x ~/jarvis_baslat.sh

# Masaüstü uygulaması için .desktop dosyası
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/jarvis.desktop << DESKTOP
[Desktop Entry]
Name=J.A.R.V.I.S.
Comment=Multi-Agent AI Asistan
Exec=bash -c "cd $(pwd) && source ~/.bashrc && python3 jarvis_web.py"
Icon=$(pwd)/jarvis_icon.svg
Terminal=true
Type=Application
Categories=Utility;AI;
DESKTOP

# SVG ikon
cat > $(pwd)/jarvis_icon.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" fill="#000810"/>
<polygon points="32,4 56,18 56,46 32,60 8,46 8,18" fill="none" stroke="#00d4ff" stroke-width="2"/>
<text x="32" y="42" text-anchor="middle" font-family="monospace" font-size="24" font-weight="bold" fill="#00d4ff">J</text>
</svg>
SVG

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Kurulum Tamamlandı! ✓              ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Başlatmak için:"
echo "  python3 jarvis_web.py    ← Web arayüzü"
echo "  python3 jarvis.py        ← Masaüstü GUI"
echo ""
echo "Not: Windows PC'de LM Studio Local Server açık olmalı!"
echo "     LM Studio > Local Server > Start Server"
echo ""

read -p "Şimdi başlatılsın mı? [E/h]: " START
if [[ "$START" =~ ^[Ee]$ ]] || [ -z "$START" ]; then
    python3 jarvis_web.py
fi
