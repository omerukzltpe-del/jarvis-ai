#!/bin/bash
# ═══════════════════════════════════════════════════
#   J.A.R.V.I.S. — Ubuntu Systemd Servis Kurulumu
#   Bilgisayar açılınca otomatik başlar
# ═══════════════════════════════════════════════════

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   J.A.R.V.I.S. Servis Kurulumu          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Değişkenler ───────────────────────────────────────────────────────────────
JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"
JARVIS_USER="$(whoami)"
PYTHON_BIN="$(which python3)"
SERVICE_NAME="jarvis"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/jarvis.env"

echo "→ Kurulum dizini : $JARVIS_DIR"
echo "→ Kullanıcı      : $JARVIS_USER"
echo "→ Python         : $PYTHON_BIN"
echo ""

# ── Ortam değişkenlerini topla ────────────────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║   Ayarlar                                ║"
echo "╚══════════════════════════════════════════╝"

# LM Studio URL
CURRENT_LM="${LM_STUDIO_URL:-http://localhost:1234/v1}"
read -p "LM Studio URL [$CURRENT_LM]: " INPUT_LM
LM_URL="${INPUT_LM:-$CURRENT_LM}"

# Anthropic API Key
CURRENT_KEY="${ANTHROPIC_API_KEY:-}"
read -p "Anthropic API Key (boş bırakılabilir) [$CURRENT_KEY]: " INPUT_KEY
ANT_KEY="${INPUT_KEY:-$CURRENT_KEY}"

# Web port
read -p "Web port [5000]: " INPUT_PORT
WEB_PORT="${INPUT_PORT:-5000}"

echo ""

# ── Ortam dosyası oluştur (/etc/jarvis.env) ───────────────────────────────────
echo "→ Ortam dosyası oluşturuluyor: $ENV_FILE"
read -p "Nextcloud Sunucu URL [örn: https://cloud.sitem.com]: " NC_URL
read -p "Nextcloud Kullanıcı Adı: " NC_USER
read -p "Nextcloud Şifre: " NC_PASS
read -p "Telegram Bot Token (boş bırakılabilir): " TG_TOKEN
read -p "Telegram Chat ID (boş bırakılabilir): " TG_CHAT
read -p "Sabah brifing saati [7]: " BRIEF_H
read -p "Sabah brifing dakikası [30]: " BRIEF_M
BRIEF_H="${BRIEF_H:-7}"
BRIEF_M="${BRIEF_M:-30}"

sudo tee "$ENV_FILE" > /dev/null << EOF
LM_STUDIO_URL=${LM_URL}
ANTHROPIC_API_KEY=${ANT_KEY}
JARVIS_PORT=${WEB_PORT}
NEXTCLOUD_URL=${NC_URL}
NEXTCLOUD_USER=${NC_USER}
NEXTCLOUD_PASS=${NC_PASS}
TELEGRAM_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}
BRIEFING_HOUR=${BRIEF_H}
BRIEFING_MINUTE=${BRIEF_M}
TZ=Europe/Istanbul
PATH=/usr/local/bin:/usr/bin:/bin:/home/${JARVIS_USER}/.npm-global/bin:/home/${JARVIS_USER}/.local/bin
HOME=/home/${JARVIS_USER}
EOF
sudo chmod 600 "$ENV_FILE"
echo "   ✓ $ENV_FILE"

# jarvis_config.py'yi LM URL ile güncelle
if [ -f "$JARVIS_DIR/jarvis_config.py" ]; then
    sed -i "s|LM_STUDIO_URL = .*|LM_STUDIO_URL = os.getenv(\"LM_STUDIO_URL\", \"${LM_URL}\")|" \
        "$JARVIS_DIR/jarvis_config.py"
    echo "   ✓ jarvis_config.py güncellendi"
fi

# ── Systemd servis dosyası ────────────────────────────────────────────────────
echo "→ Systemd servis dosyası oluşturuluyor..."
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=J.A.R.V.I.S. Multi-Agent AI Sistemi
After=network-online.target tailscaled.service
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=${JARVIS_USER}
Group=${JARVIS_USER}
WorkingDirectory=${JARVIS_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/bin/bash ${JARVIS_DIR}/hepsini_baslat.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=jarvis
TimeoutStopSec=20
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF
echo "   ✓ $SERVICE_FILE"

# ── Servisi etkinleştir ve başlat ─────────────────────────────────────────────
echo ""
echo "→ Systemd yeniden yükleniyor..."
sudo systemctl daemon-reload

echo "→ Servis etkinleştiriliyor (boot'ta otomatik başlar)..."
sudo systemctl enable "$SERVICE_NAME"

echo "→ Servis başlatılıyor..."
sudo systemctl start "$SERVICE_NAME"
sleep 2

# ── Durum kontrol ─────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Servis Durumu                          ║"
echo "╚══════════════════════════════════════════╝"
sudo systemctl status "$SERVICE_NAME" --no-pager -l

# ── Logrotate ayarı ───────────────────────────────────────────────────────────
sudo tee /etc/logrotate.d/jarvis > /dev/null << EOF
/var/log/jarvis.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
EOF

# ── Özet ─────────────────────────────────────────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ✓ Kurulum Tamamlandı!                         ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║   Web:      http://localhost:${WEB_PORT}               ║"
echo "║   Ağ:       http://${LOCAL_IP}:${WEB_PORT}        ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║   Komutlar:                                      ║"
echo "║   sudo systemctl start jarvis    → başlat        ║"
echo "║   sudo systemctl stop jarvis     → durdur        ║"
echo "║   sudo systemctl restart jarvis  → yeniden başlat║"
echo "║   sudo systemctl status jarvis   → durum         ║"
echo "║   journalctl -u jarvis -f        → canlı log     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
