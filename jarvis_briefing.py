#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Sabah Brifing Servisi
Her sabah belirli saatte:
  - Günlük takvim özeti
  - Döviz kurları (USD, EUR)
  - Akaryakıt fiyatları
  - Güncel haber başlıkları
→ Telegram + Web push bildirimi
"""

import os, json, requests, datetime, schedule, time, threading
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Ayarlar ──────────────────────────────────────────────────────────────────
BRIEFING_HOUR   = int(os.getenv("BRIEFING_HOUR",   "7"))   # sabah 7
BRIEFING_MINUTE = int(os.getenv("BRIEFING_MINUTE", "30"))  # 07:30
TIMEZONE        = os.getenv("TZ", "Europe/Istanbul")

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")

# Push bildirimi için kayıtlı aboneler (jarvis_web.py tarafından doldurulur)
_push_subscribers: list[dict] = []

TZ = ZoneInfo(TIMEZONE)


# ── Döviz Kurları ─────────────────────────────────────────────────────────────
def get_exchange_rates() -> dict:
    """Ücretsiz exchangerate-api ile döviz kuru çek."""
    results = {}
    try:
        # exchangerate.host — ücretsiz, kayıt gerektirmez
        r = requests.get(
            "https://api.exchangerate.host/latest?base=TRY&symbols=USD,EUR,GBP",
            timeout=8)
        if r.status_code == 200:
            data = r.json()
            rates = data.get("rates", {})
            # TRY bazlı → ters çevir (1 USD = kaç TRY)
            for cur, rate in rates.items():
                if rate > 0:
                    results[cur] = round(1 / rate, 2)
    except Exception:
        pass

    if not results:
        try:
            # Yedek: TCMB RSS
            r = requests.get(
                "https://www.tcmb.gov.tr/kurlar/today.xml", timeout=8)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.content)
            for cur in root.findall(".//Currency"):
                code = cur.get("CurrencyCode","")
                if code in ("USD","EUR","GBP"):
                    buying = cur.find("ForexBuying")
                    if buying is not None and buying.text:
                        results[code] = float(buying.text.replace(",","."))
        except Exception as e:
            print(f"Döviz hatası: {e}")

    return results


# ── Akaryakıt Fiyatları ───────────────────────────────────────────────────────
def get_fuel_prices() -> dict:
    """Türkiye akaryakıt fiyatlarını çek (EPDK/haberlerden)."""
    # Not: Resmi EPDK API yoktur, haber sitelerinden çekilir
    # Alternatif: yakithesaplama.com veya benzinfiyatlari.com
    prices = {}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://www.epdk.gov.tr/Detay/Icerik/3-0-24-14225",
                         headers=headers, timeout=10)
        # Basit metin taraması
        text = r.text
        import re
        # Benzin fiyatı
        m = re.search(r'benzin[^0-9]*([0-9]+[.,][0-9]+)', text, re.IGNORECASE)
        if m:
            prices["benzin"] = m.group(1).replace(",",".")
        # Motorin
        m = re.search(r'motorin[^0-9]*([0-9]+[.,][0-9]+)', text, re.IGNORECASE)
        if m:
            prices["motorin"] = m.group(1).replace(",",".")
    except Exception:
        pass

    if not prices:
        # Yedek: sabit kaynak
        try:
            r = requests.get(
                "https://www.benzinfiyatlari.net/", timeout=8,
                headers={"User-Agent":"Mozilla/5.0"})
            import re
            text = r.text
            m = re.search(r'(?:Benzin|Kurşunsuz)[^0-9]*(\d+[.,]\d+)', text, re.IGNORECASE)
            if m:
                prices["benzin"] = m.group(1)
            m = re.search(r'Motorin[^0-9]*(\d+[.,]\d+)', text, re.IGNORECASE)
            if m:
                prices["motorin"] = m.group(1)
        except Exception as e:
            print(f"Yakıt fiyatı hatası: {e}")

    # LPG için de dene
    prices.setdefault("benzin",  "—")
    prices.setdefault("motorin", "—")
    prices.setdefault("lpg",     "—")
    return prices


# ── Haber Başlıkları ──────────────────────────────────────────────────────────
def get_news_headlines(count: int = 7) -> list[str]:
    """RSS beslemelerinden Türkçe haber başlıkları."""
    headlines = []
    feeds = [
        "https://www.hurriyet.com.tr/rss/anasayfa",
        "https://www.ntv.com.tr/son-dakika.rss",
        "https://feeds.bbci.co.uk/turkce/rss.xml",
        "https://www.sabah.com.tr/rss/anasayfa.xml",
    ]
    import xml.etree.ElementTree as ET
    for feed_url in feeds:
        if len(headlines) >= count:
            break
        try:
            r = requests.get(feed_url, timeout=8,
                             headers={"User-Agent":"Mozilla/5.0"})
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:3]:
                title = item.find("title")
                if title is not None and title.text:
                    t = title.text.strip()
                    if t and t not in headlines:
                        headlines.append(t)
        except Exception:
            continue
    return headlines[:count]


# ── Takvim Özeti ─────────────────────────────────────────────────────────────
def get_calendar_summary(nc_client) -> list[dict]:
    """Nextcloud'dan bugünkü etkinlikleri getir."""
    if nc_client is None:
        return []
    try:
        return nc_client.get_today_events()
    except Exception as e:
        print(f"Takvim özeti hatası: {e}")
        return []


# ── Brifing Mesajı Oluştur ────────────────────────────────────────────────────
def build_briefing(nc_client=None) -> str:
    now = datetime.datetime.now(TZ)
    day_names = ["Pazartesi","Salı","Çarşamba","Perşembe","Cuma","Cumartesi","Pazar"]
    day_name = day_names[now.weekday()]

    lines = []
    lines.append(f"⬡ *J.A.R.V.I.S. Sabah Brifing*")
    lines.append(f"📅 {day_name}, {now.strftime('%d %B %Y')} — {now.strftime('%H:%M')}")
    lines.append("")

    # Takvim
    events = get_calendar_summary(nc_client)
    if events:
        lines.append("📆 *Bugünkü Etkinlikler:*")
        for ev in events[:5]:
            t = nc_client.format_event_time(ev.get("start","")) if nc_client else ""
            lines.append(f"  • {t} — {ev.get('title','')}")
    else:
        lines.append("📆 Bugün takvimde etkinlik yok.")
    lines.append("")

    # Döviz
    rates = get_exchange_rates()
    lines.append("💱 *Döviz Kurları:*")
    lines.append(f"  🇺🇸 USD: {rates.get('USD','—')} ₺")
    lines.append(f"  🇪🇺 EUR: {rates.get('EUR','—')} ₺")
    lines.append(f"  🇬🇧 GBP: {rates.get('GBP','—')} ₺")
    lines.append("")

    # Yakıt
    fuel = get_fuel_prices()
    lines.append("⛽ *Akaryakıt Fiyatları:*")
    lines.append(f"  Benzin:  {fuel.get('benzin','—')} ₺/L")
    lines.append(f"  Motorin: {fuel.get('motorin','—')} ₺/L")
    lines.append(f"  LPG:     {fuel.get('lpg','—')} ₺/L")
    lines.append("")

    # Haberler
    headlines = get_news_headlines(6)
    if headlines:
        lines.append("📰 *Güncel Haberler:*")
        for h in headlines:
            lines.append(f"  • {h}")

    lines.append("")
    lines.append("_İyi günler dilerim, efendim. — J.A.R.V.I.S._")

    return "\n".join(lines)


# ── Telegram Gönder ───────────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("Telegram token/chat_id ayarlanmamış, atlanıyor.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": message,
                  "parse_mode": "Markdown"},
            timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram hatası: {e}")
        return False


# ── Web Push ──────────────────────────────────────────────────────────────────
def send_web_push(title: str, body: str) -> int:
    """Kayıtlı tüm push abonelerine bildirim gönder."""
    if not _push_subscribers:
        return 0
    try:
        from pywebpush import webpush, WebPushException
        VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY","")
        VAPID_EMAIL   = os.getenv("VAPID_EMAIL","mailto:jarvis@local")
        if not VAPID_PRIVATE:
            return 0
        sent = 0
        for sub in _push_subscribers:
            try:
                webpush(
                    subscription_info=sub,
                    data=json.dumps({"title":title,"body":body[:200]}),
                    vapid_private_key=VAPID_PRIVATE,
                    vapid_claims={"sub": VAPID_EMAIL}
                )
                sent += 1
            except WebPushException as e:
                if e.response and e.response.status_code == 410:
                    _push_subscribers.remove(sub)
        return sent
    except ImportError:
        print("pywebpush kurulu değil: pip install pywebpush")
        return 0


# ── Brifing Çalıştır ─────────────────────────────────────────────────────────
def run_briefing(nc_client=None):
    print(f"[{datetime.datetime.now()}] Sabah brifing başlıyor...")
    msg = build_briefing(nc_client)
    # Telegram
    ok = send_telegram(msg)
    print(f"  Telegram: {'✓' if ok else '✗'}")
    # Web push
    sent = send_web_push("⬡ J.A.R.V.I.S. Sabah Brifing", msg[:200])
    print(f"  Web push: {sent} abone")
    return msg


# ── Zamanlayıcı (cron benzeri) ────────────────────────────────────────────────
def start_scheduler(nc_client=None):
    """Arka planda zamanlayıcı başlat."""
    briefing_time = f"{BRIEFING_HOUR:02d}:{BRIEFING_MINUTE:02d}"
    print(f"Sabah brifing zamanı: {briefing_time} ({TIMEZONE})")

    schedule.every().day.at(briefing_time).do(run_briefing, nc_client=nc_client)

    def _loop():
        while True:
            schedule.run_pending()
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("Zamanlayıcı başlatıldı.")
    return t


# ── Manuel test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Sabah brifing test ediliyor...")
    msg = build_briefing()
    print(msg)
    print("\nTelegram'a gönderiliyor...")
    send_telegram(msg)
