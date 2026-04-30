#!/bin/bash
# J.A.R.V.I.S. Servis Yönetim Aracı

case "$1" in
  baslat|start)
    sudo systemctl start jarvis
    echo "✓ JARVIS başlatıldı"
    ;;
  durdur|stop)
    sudo systemctl stop jarvis
    echo "✓ JARVIS durduruldu"
    ;;
  yeniden|restart)
    sudo systemctl restart jarvis
    echo "✓ JARVIS yeniden başlatıldı"
    ;;
  durum|status)
    sudo systemctl status jarvis --no-pager -l
    ;;
  log|logs)
    journalctl -u jarvis -f --no-pager
    ;;
  guncelle|update)
    sudo systemctl restart jarvis
    echo "✓ JARVIS güncellendi ve yeniden başlatıldı"
    ;;
  *)
    echo "Kullanım: ./jarvis_servis.sh [komut]"
    echo ""
    echo "Komutlar:"
    echo "  baslat   → servisi başlat"
    echo "  durdur   → servisi durdur"
    echo "  yeniden  → servisi yeniden başlat"
    echo "  durum    → servis durumunu göster"
    echo "  log      → canlı logları izle"
    echo "  guncelle → kodu güncelleyip yeniden başlat"
    ;;
esac
