# ⬡ J.A.R.V.I.S. — Multi-Agent AI Asistan
<img width="1871" height="933" alt="image" src="https://github.com/user-attachments/assets/158b5c03-492b-47ee-9ab7-eab1b6a0b761" />

## Dosya Yapısı

| Dosya | Açıklama |
|-------|----------|
| jarvis_config.py | Tüm ayarlar (LM URL, modeller) |
| jarvis_engine.py | Ortak AI motoru |
| jarvis_web.py | Web arayüzü (Flask) |
| jarvis.py | Masaüstü GUI (tkinter) |
| jarvis_face.py | Hologram animasyon |
| jarvis_nextcloud.py | Nextcloud entegrasyonu |
| jarvis_briefing.py | Sabah brifing servisi |
| jarvis_bot.py | Telegram botu |
| servis_kur.sh | Ubuntu systemd servis kurulumu |
| ubuntu_kur.sh | Ubuntu ilk kurulum |
| vapid_olustur.py | Web push VAPID anahtar üreteci |

---

## Ubuntu Kurulum (Sırasıyla)

### 1. Bağımlılıkları kur
```bash
chmod +x ubuntu_kur.sh
./ubuntu_kur.sh
```

### 2. Python paketleri
```bash
pip3 install -r requirements.txt --break-system-packages
```

### 3. Gemini CLI kur (ücretsiz)
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
npm install -g @google/gemini-cli
gemini auth login
```

### 4. Servisi kur (otomatik başlangıç)
```bash
chmod +x servis_kur.sh
./servis_kur.sh
```
Script şunları sorar:
- LM Studio Tailscale IP
- Anthropic API key
- Nextcloud URL / kullanıcı / şifre
- Telegram token + chat ID
- Sabah brifing saati (varsayılan 07:30)

### 5. Web Push bildirimleri (opsiyonel)
```bash
python3 vapid_olustur.py
```

---

## Nextcloud Bağlantısı

jarvis.env veya ortam değişkenleri:
```
NEXTCLOUD_URL=https://cloud.siteadresiniz.com
NEXTCLOUD_USER=kullanici_adiniz
NEXTCLOUD_PASS=sifreniz
```

JARVIS şunları yapabilir:
- Bugünkü takvim etkinliklerini okuma
- Yeni etkinlik ekleme
- Notları okuma / oluşturma
- Görevleri listeleme
- WebDAV ile dosya okuma/yazma

---

## Sabah Brifing

Her sabah 07:30'da otomatik olarak:
- Takvim özeti
- USD/EUR/GBP döviz kurları
- Benzin/Motorin/LPG fiyatları
- 7 güncel haber başlığı

Hem Telegram'a hem web push ile Samsung S24+'a gelir.

---

## Samsung Galaxy S24+ Entegrasyonu

### PWA (Ana Ekrana Ekle)
1. Chrome ile JARVIS adresini aç
2. "Ana ekrana ekle" banner'ına tıkla
3. JARVIS simgesi ana ekranda görünür
4. Tam ekran uygulama gibi açılır

### Bildirimler
1. JARVIS web arayüzünde sağ üstteki "🔔 Bildirim" butonuna bas
2. İzin ver
3. Artık sabah brifing ve önemli hatırlatmalar Samsung'a gelir

---

## LM Studio (Windows → Ubuntu Tailscale)

Windows'ta LM Studio ayarı:
1. LM Studio > Settings > Server
2. "Allow connections from network" kutusunu işaretle
3. Start Server

Ubuntu'da jarvis.env:
```
LM_STUDIO_URL=http://100.x.x.x:1234/v1
```

---

## Servis Komutları

```bash
./jarvis_servis.sh baslat    # başlat
./jarvis_servis.sh durdur    # durdur
./jarvis_servis.sh yeniden   # yeniden başlat
./jarvis_servis.sh durum     # durum
./jarvis_servis.sh log       # canlı log
```

---

"Sistemler hazır. Emrinizdeyim efendim. — J.A.R.V.I.S."
