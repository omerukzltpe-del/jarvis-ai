#!/usr/bin/env python3
"""
J.A.R.V.I.S. Web — WebSocket ile gerçek zamanlı sohbet senkronizasyonu
Tüm cihazlar (tablet, telefon, masaüstü, Telegram) aynı sohbeti paylaşır
"""

import os, json, threading, socket, datetime
from pathlib import Path
from flask import Flask, request, jsonify, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

from jarvis_config import *
from jarvis_engine import AgentEngine, Memory, prepare_file
from jarvis_nextcloud import NextcloudClient
from jarvis_briefing import (start_scheduler, run_briefing,
                              get_exchange_rates, get_fuel_prices,
                              get_news_headlines, _push_subscribers)
from jarvis_db import (save_message, get_messages, get_ai_history,
                       get_sessions, clear_session, init_db)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("JARVIS_SECRET", "jarvis-secret-2024")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

engine = AgentEngine()

# Nextcloud
NC_URL  = os.getenv("NEXTCLOUD_URL","")
NC_USER = os.getenv("NEXTCLOUD_USER","")
NC_PASS = os.getenv("NEXTCLOUD_PASS","")
nc = NextcloudClient(NC_URL, NC_USER, NC_PASS) if NC_URL else None

VAPID_PUBLIC  = os.getenv("VAPID_PUBLIC_KEY","")
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY","")
VAPID_EMAIL   = os.getenv("VAPID_EMAIL","mailto:jarvis@local")

ALLOWED_EXT = {".jpg",".jpeg",".png",".gif",".webp",
               ".pdf",".txt",".md",".py",".js",".ts",
               ".json",".csv",".html",".css",".sh",".bat",".yaml",".yml"}

start_scheduler(nc_client=nc)
init_db()


def broadcast_message(msg_data: dict, session: str = "default"):
    """Tüm bağlı cihazlara mesaj yayınla (WebSocket)."""
    socketio.emit("new_message", msg_data, room=session)


def get_reply_and_broadcast(user_text: str, mode: str,
                             session: str = "default",
                             source: str = "web",
                             file_data: dict = None):
    """AI yanıtı üret ve tüm cihazlara yayınla."""
    chosen = engine.route(user_text) if mode == "auto" else mode
    m = MODELS[chosen]

    # Nextcloud bağlam
    nc_context = ""
    low = user_text.lower()
    if nc:
        if any(k in low for k in ["takvim","etkinlik","bugün ne var","randevu"]):
            events = nc.get_today_events()
            if events:
                nc_context += "\n[Bugünkü takvim]\n" + "\n".join(
                    f"- {nc.format_event_time(e.get('start',''))} {e.get('title','')}"
                    for e in events[:5]) + "\n"
        if any(k in low for k in ["not","notlarım","kaydet"]):
            notes = nc.get_notes()
            if notes:
                nc_context += "\n[Notlar]\n" + "\n".join(
                    f"- {n['title']}: {n['content'][:100]}"
                    for n in notes[:5]) + "\n"

    full_text = (nc_context + user_text) if nc_context else user_text
    hist = get_ai_history(session, 40)

    # Dosya metnini LM için geçmişe göm
    if file_data and m["type"] == "lm" and file_data.get("text"):
        hist.append({"role":"user",
                     "content": f"[{file_data['name']}]:\n{file_data['text'][:4000]}\n\n{user_text}"})
        file_data = None
    else:
        hist.append({"role": "user", "content": full_text})

    # "Düşünüyor" sinyali yayınla
    socketio.emit("thinking", {"model": m["name"], "session": session}, room=session)

    try:
        if m["type"] in ("claude","gemini"):
            reply = engine.chat(chosen, hist, file_data=file_data)
        else:
            # LM streaming — parça parça yayınla
            parts = []
            chunk_buf = []

            def on_chunk(delta):
                parts.append(delta)
                chunk_buf.append(delta)
                if len(chunk_buf) >= 5:
                    socketio.emit("stream_chunk", {
                        "delta": "".join(chunk_buf),
                        "model": chosen, "session": session
                    }, room=session)
                    chunk_buf.clear()

            reply = engine.chat(chosen, hist, on_chunk=on_chunk)
            if chunk_buf:
                socketio.emit("stream_chunk", {
                    "delta": "".join(chunk_buf),
                    "model": chosen, "session": session
                }, room=session)

        # Nextcloud yazma
        if nc and any(k in low for k in ["not kaydet","bunu kaydet","not al"]):
            ok = nc.create_note(
                f"JARVIS — {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}",
                user_text, "JARVIS")
            if ok:
                reply += "\n\n✅ Nextcloud'a kaydedildi."

    except Exception as e:
        import anthropic, openai
        err = str(e)
        if "AuthenticationError" in type(e).__name__:
            reply = "Claude API anahtarı geçersiz veya kredi bitti."
            chosen = "error"
        elif "APIConnectionError" in type(e).__name__:
            reply = f"LM Studio bağlantısı yok!\nURL: {LM_STUDIO_URL}"
            chosen = "error"
        else:
            reply = f"Hata: {err[:300]}"
            chosen = "error"

    # DB'ye kaydet
    msg_id = save_message("assistant", reply, model=chosen,
                          source="jarvis", session=session)

    # Tüm cihazlara yayınla
    msg_data = {
        "id": msg_id,
        "role": "assistant",
        "content": reply,
        "model": chosen,
        "model_name": MODELS.get(chosen, {}).get("name", chosen),
        "source": "jarvis",
        "session": session,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }
    broadcast_message(msg_data, session)

    # Telegram'a da ilet (Telegram kaynaklı değilse)
    if source != "telegram":
        _relay_to_telegram(reply, session)

    return reply, chosen


def _relay_to_telegram(text: str, session: str):
    """Web'den gelen yanıtı Telegram'a ilet."""
    token   = os.getenv("TELEGRAM_TOKEN","")
    chat_id = os.getenv("TELEGRAM_CHAT_ID","")
    if not token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id,
                  "text": f"🤖 {text[:4000]}",
                  "parse_mode": "Markdown"},
            timeout=8
        )
    except Exception:
        pass


# ── WebSocket Events ──────────────────────────────────────────────────────────
@socketio.on("join")
def on_join(data):
    session = data.get("session", "default")
    join_room(session)
    # Geçmiş mesajları gönder
    msgs = get_messages(session, 50)
    emit("history", {"messages": msgs, "session": session})

@socketio.on("leave")
def on_leave(data):
    session = data.get("session", "default")
    leave_room(session)

@socketio.on("send_message")
def on_send_message(data):
    text    = data.get("text","").strip()
    mode    = data.get("mode","auto")
    session = data.get("session","default")
    source  = data.get("source","web")

    if not text:
        return

    # Kullanıcı mesajını DB'ye kaydet ve yayınla
    msg_id = save_message("user", text, source=source, session=session)
    broadcast_message({
        "id": msg_id,
        "role": "user",
        "content": text,
        "source": source,
        "session": session,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }, session)

    # AI yanıtı arka planda üret
    threading.Thread(
        target=get_reply_and_broadcast,
        args=(text, mode, session, source),
        daemon=True
    ).start()


# ── PWA & SW ─────────────────────────────────────────────────────────────────
MANIFEST = json.dumps({
    "name":"J.A.R.V.I.S.",
    "short_name":"JARVIS",
    "description":"Just A Rather Very Intelligent System",
    "start_url":"/",
    "display":"standalone",
    "background_color":"#000810",
    "theme_color":"#00d4ff",
    "orientation":"portrait",
    "icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]
})

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
<rect width="192" height="192" fill="#000810"/>
<polygon points="96,16 168,58 168,134 96,176 24,134 24,58"
  fill="none" stroke="#00d4ff" stroke-width="5"/>
<text x="96" y="118" text-anchor="middle"
  font-family="monospace" font-size="60" font-weight="bold" fill="#00d4ff">J</text>
</svg>"""

SW_JS = """
const CACHE='jarvis-v2';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>clients.claim());
self.addEventListener('fetch',e=>{
  e.respondWith(fetch(e.request).catch(()=>new Response('Çevrimdışı',{status:503})));
});
self.addEventListener('push',e=>{
  const d=e.data?e.data.json():{title:'JARVIS',body:'Bildirim'};
  e.waitUntil(self.registration.showNotification(d.title||'J.A.R.V.I.S.',{
    body:d.body||'',icon:'/icon.svg',badge:'/icon.svg',
    vibrate:[200,100,200],tag:'jarvis'
  }));
});
self.addEventListener('notificationclick',e=>{
  e.notification.close();
  e.waitUntil(clients.openWindow('/'));
});
"""

HTML = r"""<!DOCTYPE html>
<html lang="tr" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="theme-color" content="#0f172a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="JARVIS">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon.svg">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<title>J.A.R.V.I.S.</title>
<style>
/* ── CSS Variables ── */
:root {
  --r: 16px;
  --r-sm: 10px;
  --r-lg: 24px;
  --shadow: 0 4px 24px rgba(0,0,0,.18);
  --shadow-sm: 0 2px 8px rgba(0,0,0,.12);
  --trans: all .25s cubic-bezier(.4,0,.2,1);
}
[data-theme="dark"] {
  --bg:        #0f172a;
  --surface:   #1e293b;
  --surface2:  #273448;
  --border:    #334155;
  --text:      #e2e8f0;
  --text-sub:  #94a3b8;
  --accent:    #38bdf8;
  --accent2:   #818cf8;
  --green:     #34d399;
  --orange:    #fb923c;
  --red:       #f87171;
  --yellow:    #fbbf24;
  --user-bg:   #1e40af;
  --user-text: #eff6ff;
  --bot-bg:    #1e293b;
  --bot-text:  #e2e8f0;
}
[data-theme="light"] {
  --bg:        #f1f5f9;
  --surface:   #ffffff;
  --surface2:  #f8fafc;
  --border:    #e2e8f0;
  --text:      #0f172a;
  --text-sub:  #64748b;
  --accent:    #0284c7;
  --accent2:   #6366f1;
  --green:     #059669;
  --orange:    #ea580c;
  --red:       #dc2626;
  --yellow:    #d97706;
  --user-bg:   #0284c7;
  --user-text: #ffffff;
  --bot-bg:    #ffffff;
  --bot-text:  #0f172a;
}

/* ── Reset ── */
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;}
body{
  background:var(--bg);color:var(--text);
  font-family:'Outfit',sans-serif;font-size:15px;
  height:100vh;height:100dvh;display:flex;flex-direction:column;overflow:hidden;
  transition:background .3s,color .3s;
}

/* ── Header ── */
header{
  display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;background:var(--surface);
  border-bottom:1px solid var(--border);flex-shrink:0;
  box-shadow:var(--shadow-sm);
}
.logo{display:flex;align-items:center;gap:10px;}
.logo-icon{
  width:36px;height:36px;border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:flex;align-items:center;justify-content:center;
  font-size:16px;font-weight:700;color:#fff;
  box-shadow:0 0 16px rgba(56,189,248,.3);
}
.logo-text{font-size:1rem;font-weight:600;letter-spacing:.5px;}
.logo-sub{font-size:.65rem;color:var(--text-sub);font-family:'JetBrains Mono',monospace;}
.hdr-right{display:flex;align-items:center;gap:8px;}

/* ── Model seçici ── */
.model-select{
  background:var(--surface2);color:var(--text);
  border:1px solid var(--border);
  padding:6px 10px;font-family:'Outfit',sans-serif;
  font-size:.8rem;border-radius:var(--r-sm);
  cursor:pointer;outline:none;transition:var(--trans);
}
.model-select:hover{border-color:var(--accent);}

/* ── İkon butonlar ── */
.icon-btn{
  width:36px;height:36px;border-radius:50%;border:none;
  background:var(--surface2);color:var(--text-sub);
  display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:var(--trans);font-size:16px;
}
.icon-btn:hover{background:var(--border);color:var(--text);}
.icon-btn.active{background:var(--accent);color:#fff;}

/* ── Model chips ── */
.model-bar{
  display:flex;gap:6px;padding:8px 16px;overflow-x:auto;
  background:var(--surface);border-bottom:1px solid var(--border);
  flex-shrink:0;scrollbar-width:none;
}
.model-bar::-webkit-scrollbar{display:none;}
.chip{
  padding:4px 12px;border-radius:20px;font-size:.72rem;font-weight:500;
  border:1.5px solid var(--border);white-space:nowrap;
  opacity:.55;transition:var(--trans);cursor:pointer;
  background:var(--surface2);color:var(--text-sub);
}
.chip.active{opacity:1;border-color:currentColor;
  box-shadow:0 0 10px -2px currentColor;}

/* ── Tabs ── */
.tabs{
  display:flex;background:var(--surface);
  border-bottom:1px solid var(--border);flex-shrink:0;
}
.tab{
  flex:1;padding:10px 4px;text-align:center;font-size:.78rem;
  font-weight:500;cursor:pointer;color:var(--text-sub);
  border-bottom:2px solid transparent;transition:var(--trans);
}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);}
.tab:hover{color:var(--text);}

/* ── Panels ── */
.panel{display:none;flex:1;overflow-y:auto;flex-direction:column;}
.panel.active{display:flex;}

/* ── FACE Canvas ── */
#face-wrap{
  flex-shrink:0;display:flex;justify-content:center;
  background:var(--bg);padding:4px 0;
}
#face{display:block;}
#status-text{
  text-align:center;font-size:.7rem;color:var(--text-sub);
  font-family:'JetBrains Mono',monospace;
  letter-spacing:1.5px;padding:3px 0;flex-shrink:0;
}

/* ── Sessions ── */
#sessions-bar{
  display:flex;gap:6px;padding:8px 14px;overflow-x:auto;
  background:var(--surface2);border-bottom:1px solid var(--border);
  flex-shrink:0;scrollbar-width:none;
}
#sessions-bar::-webkit-scrollbar{display:none;}
.sess-btn{
  padding:4px 14px;border-radius:20px;font-size:.72rem;
  font-weight:500;cursor:pointer;white-space:nowrap;
  background:var(--surface);color:var(--text-sub);
  border:1.5px solid var(--border);transition:var(--trans);
  font-family:'Outfit',sans-serif;
}
.sess-btn.active{
  color:var(--accent);border-color:var(--accent);
  background:var(--surface2);
}

/* ── Chat ── */
#msg-list{
  flex:1;overflow-y:auto;padding:16px 14px;
  display:flex;flex-direction:column;gap:10px;
  scroll-behavior:smooth;
}
.msg{
  max-width:88%;padding:10px 14px;
  border-radius:var(--r-lg);
  font-size:.88rem;line-height:1.6;
  white-space:pre-wrap;word-break:break-word;
  animation:msgIn .2s ease;
}
@keyframes msgIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.msg.user{
  background:var(--user-bg);color:var(--user-text);
  align-self:flex-end;
  border-bottom-right-radius:4px;
  box-shadow:var(--shadow-sm);
}
.msg.assistant{
  background:var(--bot-bg);color:var(--bot-text);
  align-self:flex-start;
  border-bottom-left-radius:4px;
  border:1px solid var(--border);
  box-shadow:var(--shadow-sm);
}
.msg.system-msg{
  background:transparent;border:1px dashed var(--border);
  color:var(--text-sub);font-size:.72rem;
  align-self:center;text-align:center;
  border-radius:var(--r);padding:6px 14px;
}
.msg.error-msg{
  background:#fee2e2;border:1px solid #fca5a5;
  color:#991b1b;align-self:flex-start;
  border-radius:var(--r-lg);border-bottom-left-radius:4px;
}
[data-theme="dark"] .msg.error-msg{
  background:#2d1515;border-color:#7f1d1d;color:#fca5a5;
}
.msg-meta{
  font-size:.62rem;color:var(--text-sub);
  margin-bottom:4px;display:flex;gap:6px;align-items:center;
  font-family:'JetBrains Mono',monospace;
}
.src-badge{
  padding:1px 6px;border-radius:20px;
  border:1px solid currentColor;opacity:.7;font-size:.6rem;
}

/* ── Typing ── */
.typing-dots{display:inline-flex;gap:4px;padding:4px 0;}
.typing-dots span{
  width:7px;height:7px;border-radius:50%;
  background:var(--accent);animation:dot 1.2s infinite;
}
.typing-dots span:nth-child(2){animation-delay:.2s;}
.typing-dots span:nth-child(3){animation-delay:.4s;}
@keyframes dot{0%,60%,100%{opacity:.2;transform:scale(.8)}30%{opacity:1;transform:scale(1)}}

/* ── NC & Briefing panels ── */
.sub-panel{padding:14px;display:flex;flex-direction:column;gap:10px;}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);padding:14px;
  box-shadow:var(--shadow-sm);
}
.card h3{font-size:.82rem;font-weight:600;color:var(--accent);margin-bottom:8px;}
.nc-item{
  padding:7px 0;border-bottom:1px solid var(--border);
  font-size:.8rem;color:var(--text);
}
.nc-item:last-child{border-bottom:none;}
.brief-row{
  display:flex;justify-content:space-between;
  padding:6px 0;border-bottom:1px solid var(--border);font-size:.82rem;
}
.brief-row:last-child{border-bottom:none;}
.brief-label{color:var(--text-sub);}
.brief-val{color:var(--green);font-weight:600;font-family:'JetBrains Mono',monospace;}

/* ── Input ── */
.input-wrap{
  padding:10px 14px;background:var(--surface);
  border-top:1px solid var(--border);flex-shrink:0;
  box-shadow:0 -2px 12px rgba(0,0,0,.06);
}
.file-area{
  display:flex;align-items:center;gap:6px;
  margin-bottom:8px;min-height:24px;
}
#file-info{
  flex:1;font-size:.72rem;color:var(--green);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.input-row{display:flex;gap:8px;align-items:flex-end;margin-bottom:8px;}
#inp{
  flex:1;background:var(--surface2);color:var(--text);
  border:1.5px solid var(--border);
  padding:10px 14px;font-family:'Outfit',sans-serif;
  font-size:.9rem;border-radius:var(--r);
  outline:none;resize:none;
  min-height:44px;max-height:110px;
  transition:var(--trans);line-height:1.5;
}
#inp:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(56,189,248,.15);}
#inp::placeholder{color:var(--text-sub);}

/* ── Butonlar ── */
.btn{
  border:none;cursor:pointer;font-family:'Outfit',sans-serif;
  font-weight:500;transition:var(--trans);border-radius:var(--r);
  display:flex;align-items:center;justify-content:center;gap:6px;
}
.btn:active{transform:scale(.96);}
.btn-primary{
  background:var(--accent);color:#fff;
  padding:10px 18px;font-size:.85rem;
  box-shadow:0 2px 10px rgba(56,189,248,.25);
}
.btn-primary:hover{filter:brightness(1.1);}
.btn-mic{
  width:44px;height:44px;border-radius:50%;
  background:var(--surface2);color:var(--accent2);
  border:1.5px solid var(--border);font-size:18px;
}
.btn-mic.on{background:var(--red);color:#fff;border-color:var(--red);}
.btn-stop{
  width:44px;height:44px;border-radius:50%;
  background:var(--surface2);color:var(--green);
  border:1.5px solid var(--border);font-size:16px;
  display:none;
}
.btn-file{
  background:var(--surface2);color:var(--green);
  border:1.5px solid var(--border);
  padding:5px 12px;border-radius:var(--r-sm);
  font-size:.75rem;cursor:pointer;font-family:'Outfit',sans-serif;
  transition:var(--trans);
}
.btn-file:hover{border-color:var(--green);}
.btn-clf{
  background:transparent;color:var(--red);border:none;
  font-size:14px;cursor:pointer;padding:2px 6px;
  border-radius:var(--r-sm);display:none;transition:var(--trans);
}
.btn-clf:hover{background:var(--surface2);}
#file-input{display:none;}

/* ── Quick butonlar ── */
.quick-row{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;}
.quick-row::-webkit-scrollbar{display:none;}
.qbtn{
  background:var(--surface2);color:var(--text-sub);
  border:1.5px solid var(--border);
  padding:5px 12px;font-size:.72rem;font-weight:500;
  border-radius:20px;white-space:nowrap;cursor:pointer;
  font-family:'Outfit',sans-serif;transition:var(--trans);
}
.qbtn:hover{border-color:var(--accent);color:var(--accent);}

/* ── Install bar ── */
#install-bar{
  display:none;padding:8px 16px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  align-items:center;justify-content:space-between;
  font-size:.78rem;color:#fff;flex-shrink:0;
}
#install-bar .btn-sm{
  background:rgba(255,255,255,.2);color:#fff;border:none;
  padding:4px 12px;border-radius:20px;cursor:pointer;
  font-size:.75rem;font-family:'Outfit',sans-serif;
}
</style>
</head>
<body>

<div id="install-bar">
  <span>📱 Ana ekrana ekle</span>
  <div style="display:flex;gap:6px">
    <button class="btn-sm" onclick="installPWA()">Ekle</button>
    <button class="btn-sm" onclick="document.getElementById('install-bar').style.display='none'">×</button>
  </div>
</div>

<header>
  <div class="logo">
    <div class="logo-icon">J</div>
    <div>
      <div class="logo-text">J.A.R.V.I.S.</div>
      <div class="logo-sub">MULTI-AGENT · SYNC</div>
    </div>
  </div>
  <div class="hdr-right">
    <span id="sync-dot" style="width:8px;height:8px;border-radius:50%;background:#f87171;display:inline-block;transition:background .3s" title="Bağlantı"></span>
    <select class="model-select" id="model-sel" onchange="setMode(this.value)">
      <option value="auto">⚡ Otomatik</option>
      <option value="gemma">🟣 Gemma 3</option>
      <option value="deepseek">🔴 DeepSeek R1</option>
      <option value="llama">🦙 Llama 3.1</option>
      <option value="claude">🔵 Claude</option>
      <option value="gemini">🟢 Gemini 2.5</option>
      <option value="abacus">⚡ Abacus AI</option>
    </select>
    <button class="icon-btn" onclick="toggleTheme()" id="theme-btn" title="Tema değiştir">🌙</button>
    <button class="icon-btn" onclick="enableNotifications()" title="Bildirimler">🔔</button>
    <button class="icon-btn" onclick="newSession()" title="Yeni sohbet">✏️</button>
  </div>
</header>

<div class="model-bar">
  <div class="chip active" style="color:#a78bfa" id="chip-gemma">🟣 Gemma 3</div>
  <div class="chip" style="color:#f87171" id="chip-deepseek">🔴 DeepSeek</div>
  <div class="chip" style="color:#fb923c" id="chip-llama">🦙 Llama 3.1</div>
  <div class="chip" style="color:#38bdf8" id="chip-claude">🔵 Claude</div>
  <div class="chip" style="color:#34d399" id="chip-gemini">🟢 Gemini 2.5</div>
  <div class="chip" style="color:#fbbf24" id="chip-abacus">⚡ Abacus</div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('chat')">💬 Sohbet</div>
  <div class="tab" onclick="switchTab('nc')">☁️ Nextcloud</div>
  <div class="tab" onclick="switchTab('brief')">🌅 Brifing</div>
</div>

<!-- CHAT PANEL -->
<div class="panel active" id="panel-chat">
  <div id="face-wrap">
    <canvas id="face" width="300" height="170"></canvas>
  </div>
  <div id="status-text">● HAZIR</div>

  <div id="sessions-bar">
    <button class="sess-btn active" id="sess-default" onclick="switchSession('default')">💬 Ana</button>
  </div>

  <div id="msg-list">
    <div class="msg system-msg">⬡ J.A.R.V.I.S. bağlanıyor...</div>
  </div>
</div>

<!-- NC PANEL -->
<div class="panel" id="panel-nc">
  <div class="sub-panel">
    <div class="card">
      <h3>📅 Bugünkü Takvim</h3>
      <div id="nc-events"><div class="nc-item" style="color:var(--text-sub)">Yükleniyor...</div></div>
    </div>
    <div class="card">
      <h3>📝 Son Notlar</h3>
      <div id="nc-notes"><div class="nc-item" style="color:var(--text-sub)">Yükleniyor...</div></div>
    </div>
    <div class="card">
      <h3>✅ Görevler</h3>
      <div id="nc-tasks"><div class="nc-item" style="color:var(--text-sub)">Yükleniyor...</div></div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="qbtn" onclick="ncRefresh()">🔄 Yenile</button>
      <button class="qbtn" onclick="ncAddEvent()">➕ Etkinlik</button>
      <button class="qbtn" onclick="ncAddNote()">📝 Not Ekle</button>
    </div>
  </div>
</div>

<!-- BRİFİNG PANEL -->
<div class="panel" id="panel-brief">
  <div class="sub-panel">
    <div class="card">
      <h3>💱 Döviz Kurları</h3>
      <div id="brief-rates"><div style="color:var(--text-sub);font-size:.8rem">Yükleniyor...</div></div>
    </div>
    <div class="card">
      <h3>⛽ Akaryakıt</h3>
      <div id="brief-fuel"><div style="color:var(--text-sub);font-size:.8rem">Yükleniyor...</div></div>
    </div>
    <div class="card">
      <h3>📰 Güncel Haberler</h3>
      <div id="brief-news"><div style="color:var(--text-sub);font-size:.8rem">Yükleniyor...</div></div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="qbtn" onclick="loadBriefing()">🔄 Güncelle</button>
      <button class="qbtn" onclick="sendBriefingNow()">📨 Telegram'a Gönder</button>
    </div>
  </div>
</div>

<!-- INPUT -->
<div class="input-wrap">
  <div class="file-area">
    <button class="btn-file" onclick="document.getElementById('file-input').click()">📎 Dosya</button>
    <span id="file-info"></span>
    <button class="btn-clf btn" id="clf-btn" onclick="clearFile()">✕</button>
    <input type="file" id="file-input"
      accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.txt,.md,.py,.js,.json,.csv"
      onchange="fileSelected(this)">
  </div>
  <div class="input-row">
    <textarea id="inp" placeholder="Bir şeyler yazın..." rows="1"
      onkeydown="onKey(event)" oninput="resize(this)"></textarea>
    <button class="btn btn-primary" onclick="send()">Gönder</button>
    <button class="btn btn-mic" id="mic-btn" onclick="toggleMic()">🎙</button>
    <button class="btn btn-stop" id="stop-btn" onclick="stopSpeech()">⏹</button>
  </div>
  <div class="quick-row">
    <button class="qbtn" onclick="quick('Bugün takvimde ne var?')">📅 Bugün</button>
    <button class="qbtn" onclick="quick('Dolar kaç?')">💱 Döviz</button>
    <button class="qbtn" onclick="quick('Haberleri özetle')">🌐 Haber</button>
    <button class="qbtn" onclick="quick('Notlarımı göster')">📝 Notlar</button>
    <button class="qbtn" onclick="clearCurrentSession()">🗑 Temizle</button>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<script>
// ══ THEME ══
let theme = localStorage.getItem('jarvis-theme') || 'dark';
document.documentElement.setAttribute('data-theme', theme);
document.getElementById('theme-btn').textContent = theme === 'dark' ? '☀️' : '🌙';

function toggleTheme() {
  theme = theme === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('theme-btn').textContent = theme === 'dark' ? '☀️' : '🌙';
  localStorage.setItem('jarvis-theme', theme);
}

// ══ REALISTIC 3D FACE ══
const cv  = document.getElementById('face');
const ctx = cv.getContext('2d');
const CX  = cv.width / 2, CY = cv.height / 2 + 5;

let fState = 'idle', fT = 0, wave = new Array(44).fill(0);
let mOpen = 0, ring = 0, blinkT = 0, breathT = 0;

function setFace(s) {
  fState = s;
  const labels = {
    speaking:'◉ KONUŞUYOR', thinking:'◌ DÜŞÜNÜYOR...',
    listening:'◎ DİNLİYOR', idle:'● HAZIR'
  };
  document.getElementById('status-text').textContent = labels[s] || '● HAZIR';
}

function getAccent() {
  return getComputedStyle(document.documentElement)
    .getPropertyValue('--accent').trim() || '#38bdf8';
}

function animFace() {
  fT += 0.04; ring = (ring + 1.5) % 360; blinkT += 0.03; breathT += 0.02;

  // Dalga
  const wamp = fState==='speaking'?.9 : fState==='listening'?.6 : fState==='thinking'?.3 : .08;
  wave.unshift(fState==='speaking' ? (Math.random()*2-1)*wamp :
               fState==='listening'? Math.sin(fT*9)*wamp :
               fState==='thinking' ? Math.sin(fT*4)*wamp : Math.sin(fT*1.5)*wamp);
  wave.pop();

  if (fState==='speaking') mOpen = Math.min(1, mOpen+.1);
  else mOpen = Math.max(0, mOpen-.08);

  const isDark = theme === 'dark';
  const bg     = isDark ? '#0f172a' : '#f1f5f9';
  const acc    = fState==='speaking' ? '#34d399' :
                 fState==='listening'? '#818cf8' :
                 fState==='thinking' ? '#fbbf24' : '#38bdf8';

  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, cv.width, cv.height);

  const breathScale = 1 + Math.sin(breathT) * 0.012;

  // ── Arka ışıma (glow) ──
  const grd = ctx.createRadialGradient(CX,CY,10, CX,CY,90);
  grd.addColorStop(0, acc + '22');
  grd.addColorStop(1, 'transparent');
  ctx.fillStyle = grd;
  ctx.beginPath(); ctx.arc(CX, CY, 90, 0, Math.PI*2); ctx.fill();

  // ── Dönen dış halkalar ──
  for (let i = 0; i < 340; i += 5) {
    const a1 = (i + ring) * Math.PI/180;
    const a2 = (i + 4 + ring) * Math.PI/180;
    ctx.beginPath();
    ctx.moveTo(CX + 118*Math.cos(a1)*breathScale, CY + 21*Math.sin(a1)*breathScale);
    ctx.lineTo(CX + 118*Math.cos(a2)*breathScale, CY + 21*Math.sin(a2)*breathScale);
    ctx.strokeStyle = acc; ctx.lineWidth = 1.5; ctx.stroke();
  }
  for (let i = 0; i < 340; i += 7) {
    const a1 = (i - ring*.6) * Math.PI/180;
    const a2 = (i + 6 - ring*.6) * Math.PI/180;
    ctx.beginPath();
    ctx.moveTo(CX + 22*Math.cos(a1)*breathScale, CY + 118*Math.sin(a1)*breathScale);
    ctx.lineTo(CX + 22*Math.cos(a2)*breathScale, CY + 118*Math.sin(a2)*breathScale);
    ctx.strokeStyle = acc + '55'; ctx.lineWidth = 1; ctx.stroke();
  }

  // ── Yüz ovali (3D baş şekli) ──
  const headW = 58 * breathScale, headH = 72 * breathScale;
  // Gölge / derinlik
  const headGrd = ctx.createRadialGradient(CX-8, CY-10, 5, CX, CY, headW*1.4);
  headGrd.addColorStop(0, isDark ? '#1e293b' : '#ffffff');
  headGrd.addColorStop(.6, isDark ? '#152033' : '#f0f4f8');
  headGrd.addColorStop(1, isDark ? '#0c1520' : '#dde4ee');
  ctx.beginPath();
  ctx.ellipse(CX, CY, headW, headH, 0, 0, Math.PI*2);
  ctx.fillStyle = headGrd; ctx.fill();
  ctx.strokeStyle = acc + '66'; ctx.lineWidth = 1.5; ctx.stroke();

  // ── Alın çizgisi ──
  ctx.beginPath();
  ctx.moveTo(CX - 28, CY - 50);
  ctx.quadraticCurveTo(CX, CY - 62, CX + 28, CY - 50);
  ctx.strokeStyle = acc + '33'; ctx.lineWidth = 1; ctx.stroke();

  // ── Gözler ──
  const blink = Math.abs(Math.sin(blinkT*.35)) > .96 ? 1.5 : 10;
  const eyeY  = CY - 18;

  [CX - 20, CX + 20].forEach((ex, idx) => {
    // Göz yuvası gölgesi
    const eyeGrd = ctx.createRadialGradient(ex, eyeY, 0, ex, eyeY, 14);
    eyeGrd.addColorStop(0, isDark ? '#0a1120' : '#1e293b');
    eyeGrd.addColorStop(1, 'transparent');
    ctx.beginPath(); ctx.ellipse(ex, eyeY, 14, blink, 0, 0, Math.PI*2);
    ctx.fillStyle = eyeGrd; ctx.fill();

    // Göz çerçevesi
    ctx.beginPath(); ctx.ellipse(ex, eyeY, 14, blink, 0, 0, Math.PI*2);
    ctx.strokeStyle = acc; ctx.lineWidth = 1.5; ctx.stroke();

    if (blink > 3) {
      // İris
      const irisGrd = ctx.createRadialGradient(ex-2, eyeY-2, 0, ex, eyeY, 8);
      irisGrd.addColorStop(0, acc);
      irisGrd.addColorStop(.5, acc + 'aa');
      irisGrd.addColorStop(1, acc + '33');
      ctx.beginPath(); ctx.arc(ex, eyeY, 8, 0, Math.PI*2);
      ctx.fillStyle = irisGrd; ctx.fill();

      // Pupil
      ctx.beginPath(); ctx.arc(ex, eyeY, 4, 0, Math.PI*2);
      ctx.fillStyle = '#000810'; ctx.fill();

      // Parlama
      ctx.beginPath(); ctx.arc(ex-3, eyeY-3, 2.5, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(255,255,255,.8)'; ctx.fill();
      ctx.beginPath(); ctx.arc(ex+2, eyeY+2, 1, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(255,255,255,.4)'; ctx.fill();
    }
  });

  // ── Kaşlar ──
  const browY   = eyeY - blink - 8;
  const browOff = fState === 'thinking' ? 4 : 0;
  ctx.lineWidth = 2; ctx.lineCap = 'round';
  ctx.strokeStyle = acc + 'cc';
  // Sol kaş
  ctx.beginPath();
  ctx.moveTo(CX - 33, browY + browOff);
  ctx.quadraticCurveTo(CX - 20, browY - 2, CX - 8, browY + 1);
  ctx.stroke();
  // Sağ kaş
  ctx.beginPath();
  ctx.moveTo(CX + 8, browY + 1);
  ctx.quadraticCurveTo(CX + 20, browY - 2, CX + 33, browY + browOff);
  ctx.stroke();

  // ── Burun ──
  ctx.beginPath();
  ctx.moveTo(CX - 4, CY + 2);
  ctx.quadraticCurveTo(CX - 6, CY + 14, CX - 3, CY + 17);
  ctx.moveTo(CX + 4, CY + 2);
  ctx.quadraticCurveTo(CX + 6, CY + 14, CX + 3, CY + 17);
  ctx.strokeStyle = acc + '55'; ctx.lineWidth = 1; ctx.stroke();

  // ── Ağız ──
  const mY  = CY + 30, mW = 22;
  const oh  = Math.round(mOpen * 12);
  ctx.lineCap = 'round'; ctx.lineWidth = 2;
  if (oh > 2) {
    // Açık ağız
    const mouthGrd = ctx.createLinearGradient(CX, mY-oh, CX, mY+oh);
    mouthGrd.addColorStop(0, isDark ? '#0a1120' : '#1e293b');
    mouthGrd.addColorStop(1, isDark ? '#060d18' : '#0f172a');
    ctx.beginPath();
    ctx.ellipse(CX, mY, mW, oh, 0, 0, Math.PI*2);
    ctx.fillStyle = mouthGrd; ctx.fill();
    ctx.strokeStyle = acc; ctx.lineWidth = 1.5; ctx.stroke();

    // Diş çizgisi
    ctx.beginPath(); ctx.moveTo(CX-mW+4, mY); ctx.lineTo(CX+mW-4, mY);
    ctx.strokeStyle = acc+'44'; ctx.lineWidth = 1; ctx.stroke();
  } else {
    // Kapalı — hafif gülümseme
    ctx.beginPath();
    ctx.moveTo(CX - mW, mY);
    ctx.quadraticCurveTo(CX, mY + 5, CX + mW, mY);
    ctx.strokeStyle = acc; ctx.lineWidth = 2; ctx.stroke();
  }

  // ── Yüz kontur detayları ──
  // Yanak gölgesi
  [CX-38, CX+38].forEach(x => {
    const chkGrd = ctx.createRadialGradient(x, CY+5, 0, x, CY+5, 18);
    chkGrd.addColorStop(0, acc + '18');
    chkGrd.addColorStop(1, 'transparent');
    ctx.beginPath(); ctx.arc(x, CY+5, 18, 0, Math.PI*2);
    ctx.fillStyle = chkGrd; ctx.fill();
  });

  // ── Ses dalgası ──
  const wy = CY + 68, ww = 110;
  const wamp2 = fState==='speaking'?14 : fState==='listening'?11 : fState==='thinking'?7 : 2;
  ctx.beginPath();
  wave.forEach((v, i) => {
    const x = CX - ww + (2*ww*i/(wave.length-1));
    const y = wy + v * wamp2;
    i === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
  });
  ctx.strokeStyle = acc; ctx.lineWidth = 1.8; ctx.stroke();

  // Dalga çerçevesi (yumuşak)
  ctx.strokeStyle = isDark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.08)';
  ctx.lineWidth = 1;
  const wfr = new Path2D();
  wfr.roundRect(CX-ww-4, wy-16, (ww+4)*2, 32, 8);
  ctx.stroke(wfr);

  requestAnimationFrame(animFace);
}
animFace();

// ══ TTS ══
const synth = window.speechSynthesis;
let ttsQ = [], ttsOn = false;

function splitSents(text) {
  let out = [];
  text.replace(/\[.*?\]/g,'').trim()
    .split(/(?<=[.!?…\n])\s+|(?<=\n)/g).filter(x=>x.trim())
    .forEach(s => {
      s = s.trim();
      while (s.length > 160) {
        let c = s.lastIndexOf(' ', 160); if (c < 50) c = 160;
        out.push(s.slice(0,c).trim()); s = s.slice(c).trim();
      }
      if (s) out.push(s);
    });
  return out;
}

function speakAll(text) {
  if (!synth) return;
  synth.cancel(); ttsQ = splitSents(text); ttsOn = true;
  document.getElementById('stop-btn').style.display = 'flex';
  speakNext();
}

function speakNext() {
  if (!ttsOn || !ttsQ.length) {
    setFace('idle');
    document.getElementById('stop-btn').style.display = 'none';
    return;
  }
  const utt = new SpeechSynthesisUtterance(ttsQ.shift());
  utt.lang = 'tr-TR'; utt.rate = 1.05; utt.pitch = 0.95;
  const tr = synth.getVoices().find(v => v.lang.startsWith('tr'));
  if (tr) utt.voice = tr;
  utt.onstart  = () => setFace('speaking');
  utt.onend    = utt.onerror = () => { if (ttsOn) speakNext(); };
  synth.speak(utt);
}

function stopSpeech() {
  ttsOn = false; ttsQ = []; synth.cancel(); setFace('idle');
  document.getElementById('stop-btn').style.display = 'none';
}
window.speechSynthesis.onvoiceschanged = () => {};

// ══ WebSocket ══
const socket = io({ transports: ['websocket','polling'] });
let currentSession = 'default', mode = 'auto';
let streamingDiv = null, streamingContent = '';

socket.on('connect', () => {
  document.getElementById('sync-dot').style.background = '#34d399';
  setFace('idle');
  socket.emit('join', { session: currentSession });
});
socket.on('disconnect', () => {
  document.getElementById('sync-dot').style.background = '#f87171';
  document.getElementById('status-text').textContent = '● BAĞLANTI KESİLDİ';
});

socket.on('history', data => {
  const ml = document.getElementById('msg-list');
  ml.innerHTML = '';
  if (!data.messages?.length) {
    ml.innerHTML = '<div class="msg system-msg">⬡ Yeni sohbet — Merhaba!</div>';
  } else {
    data.messages.forEach(m => appendMessage(m, false));
  }
  ml.scrollTop = ml.scrollHeight;
});

socket.on('new_message', data => {
  if (streamingDiv) { streamingDiv = null; streamingContent = ''; }
  appendMessage(data, true);
  if (data.role === 'assistant' && data.content) speakAll(data.content);
  if (data.model) setChip(data.model);
  setFace(data.role === 'user' ? 'thinking' : 'idle');
  document.getElementById('typing-indicator')?.remove();
});

socket.on('thinking', () => {
  setFace('thinking');
  const ml = document.getElementById('msg-list');
  const td = document.createElement('div');
  td.className = 'msg assistant'; td.id = 'typing-indicator';
  td.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
  ml.appendChild(td); ml.scrollTop = ml.scrollHeight;
});

socket.on('stream_chunk', data => {
  document.getElementById('typing-indicator')?.remove();
  const ml = document.getElementById('msg-list');
  const colors = {gemma:'#a78bfa',claude:'#38bdf8',gemini:'#34d399',
                  deepseek:'#f87171',llama:'#fb923c',abacus:'#fbbf24'};
  if (!streamingDiv) {
    streamingDiv = document.createElement('div');
    streamingDiv.className = 'msg assistant';
    const col = colors[data.model] || '#38bdf8';
    streamingDiv.innerHTML = `<div class="msg-meta" style="color:${col}">JARVIS [${data.model||''}]</div>`;
    streamingContent = '';
    ml.appendChild(streamingDiv);
  }
  streamingContent += data.delta;
  if (streamingDiv.childNodes[1]) {
    streamingDiv.childNodes[1].textContent = streamingContent;
  } else {
    streamingDiv.appendChild(document.createTextNode(streamingContent));
  }
  ml.scrollTop = ml.scrollHeight;
  setFace('thinking');
});

function appendMessage(m, scroll) {
  document.getElementById('typing-indicator')?.remove();
  const ml = document.getElementById('msg-list');
  const colors = {gemma:'#a78bfa',claude:'#38bdf8',gemini:'#34d399',
                  deepseek:'#f87171',llama:'#fb923c',abacus:'#fbbf24',error:'#f87171'};
  const srcIcons = {web:'🌐',telegram:'✈️',desktop:'🖥️',jarvis:'🤖'};
  const d = document.createElement('div');

  if (m.role === 'user') {
    d.className = 'msg user';
    const ts = m.timestamp || '';
    const src = srcIcons[m.source] || '🌐';
    d.innerHTML = `<div class="msg-meta">${ts} ${src}</div>` + escH(m.content || '');
  } else if (m.role === 'assistant') {
    const cls = m.model === 'error' ? 'error-msg' : 'assistant';
    d.className = 'msg ' + cls;
    const col   = colors[m.model] || '#38bdf8';
    const mname = m.model_name || m.model || 'JARVIS';
    d.innerHTML = `<div class="msg-meta" style="color:${col}">${m.timestamp||''} ${mname}</div>` + escH(m.content || '');
  } else {
    d.className = 'msg system-msg';
    d.textContent = m.content || '';
  }
  ml.appendChild(d);
  if (scroll) ml.scrollTop = ml.scrollHeight;
}

function escH(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function setChip(k) {
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  document.getElementById('chip-'+k)?.classList.add('active');
}

// ══ SESSION ══
function switchSession(id) {
  socket.emit('leave', { session: currentSession });
  currentSession = id;
  document.querySelectorAll('.sess-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('sess-'+id)?.classList.add('active');
  document.getElementById('msg-list').innerHTML = '';
  socket.emit('join', { session: id });
}

function newSession() {
  const id  = 'sess-' + Date.now();
  const bar = document.getElementById('sessions-bar');
  const btn = document.createElement('button');
  btn.className = 'sess-btn'; btn.id = 'sess-' + id;
  btn.textContent = '💬 ' + (bar.children.length + 1);
  btn.onclick = () => switchSession(id);
  bar.appendChild(btn);
  switchSession(id);
}

function clearCurrentSession() {
  if (!confirm('Bu sohbet temizlensin mi?')) return;
  fetch('/session/clear', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session: currentSession})
  }).then(() => {
    document.getElementById('msg-list').innerHTML =
      '<div class="msg system-msg">Sohbet temizlendi.</div>';
  });
}

// ══ SEND ══
let currentFile = null;
function setMode(v) { mode = v; }

async function send() {
  const el = document.getElementById('inp');
  let text = el.value.trim();
  if (!text && !currentFile) return;
  if (!text) text = 'Bu dosyayı analiz et.';
  el.value = ''; el.style.height = 'auto';
  stopSpeech(); switchTab('chat');

  if (currentFile) {
    const fd = new FormData();
    fd.append('message', text); fd.append('mode', mode);
    fd.append('session', currentSession); fd.append('file', currentFile);
    clearFile();
    await fetch('/chat_file', { method:'POST', body:fd });
  } else {
    socket.emit('send_message', {
      text, mode, session: currentSession, source: 'web'
    });
  }
}

function quick(t) { document.getElementById('inp').value = t; send(); }
function resize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 110) + 'px';
}
function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
}

function fileSelected(inp) {
  if (!inp.files.length) return;
  currentFile = inp.files[0];
  document.getElementById('file-info').textContent = `📎 ${currentFile.name}`;
  document.getElementById('clf-btn').style.display = 'block';
}
function clearFile() {
  currentFile = null;
  document.getElementById('file-input').value = '';
  document.getElementById('file-info').textContent = '';
  document.getElementById('clf-btn').style.display = 'none';
}

// ══ MİKROFON ══
let isListening = false, recognition = null;
function toggleMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('Chrome kullanın'); return; }
  if (isListening) { recognition?.stop(); return; }
  stopSpeech();
  recognition = new SR();
  recognition.lang = 'tr-TR'; recognition.interimResults = false;
  recognition.onstart  = () => {
    isListening = true;
    document.getElementById('mic-btn').classList.add('on');
    document.getElementById('mic-btn').textContent = '⏹';
    setFace('listening');
  };
  recognition.onresult = e => {
    document.getElementById('inp').value = e.results[0][0].transcript;
    send();
  };
  recognition.onend = recognition.onerror = () => {
    isListening = false;
    document.getElementById('mic-btn').classList.remove('on');
    document.getElementById('mic-btn').textContent = '🎙';
    if (fState === 'listening') setFace('idle');
  };
  recognition.start();
}

// ══ TABS ══
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    t.classList.toggle('active', ['chat','nc','brief'][i] === name);
  });
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  if (name === 'nc') ncRefresh();
  if (name === 'brief') loadBriefing();
}

// ══ NEXTCLOUD ══
async function ncRefresh() {
  try {
    const d = await (await fetch('/nc/data')).json();
    document.getElementById('nc-events').innerHTML = d.events?.length
      ? d.events.map(e=>`<div class="nc-item">🕐 ${e.start} — ${e.title}</div>`).join('')
      : '<div class="nc-item" style="color:var(--text-sub)">Bugün etkinlik yok.</div>';
    document.getElementById('nc-notes').innerHTML = d.notes?.length
      ? d.notes.map(n=>`<div class="nc-item">📝 <strong>${n.title}</strong><br><span style="color:var(--text-sub);font-size:.75rem">${n.content}</span></div>`).join('')
      : '<div class="nc-item" style="color:var(--text-sub)">Not yok.</div>';
    document.getElementById('nc-tasks').innerHTML = d.tasks?.length
      ? d.tasks.map(t=>`<div class="nc-item">☐ ${t.title}</div>`).join('')
      : '<div class="nc-item" style="color:var(--green)">✓ Tamamlandı!</div>';
  } catch(e) { console.error(e); }
}
async function ncAddEvent() {
  const title = prompt('Etkinlik adı:'); if (!title) return;
  const dt    = prompt('Tarih/saat (YYYY-MM-DD HH:MM):'); if (!dt) return;
  const r = await fetch('/nc/add_event', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({title, datetime: dt})
  });
  alert((await r.json()).ok ? '✓ Eklendi!' : 'Hata!'); ncRefresh();
}
async function ncAddNote() {
  const title   = prompt('Başlık:'); if (!title) return;
  const content = prompt('İçerik:'); if (!content) return;
  const r = await fetch('/nc/add_note', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({title, content})
  });
  alert((await r.json()).ok ? '✓ Eklendi!' : 'Hata!'); ncRefresh();
}

// ══ BRİFİNG ══
async function loadBriefing() {
  ['rates','fuel','news'].forEach(k =>
    document.getElementById('brief-'+k).innerHTML =
      '<div style="color:var(--text-sub);font-size:.8rem">Yükleniyor...</div>');
  try {
    const d = await (await fetch('/briefing/data')).json();
    const r = d.rates || {};
    document.getElementById('brief-rates').innerHTML = `
      <div class="brief-row"><span class="brief-label">🇺🇸 USD</span><span class="brief-val">${r.USD||'—'} ₺</span></div>
      <div class="brief-row"><span class="brief-label">🇪🇺 EUR</span><span class="brief-val">${r.EUR||'—'} ₺</span></div>
      <div class="brief-row"><span class="brief-label">🇬🇧 GBP</span><span class="brief-val">${r.GBP||'—'} ₺</span></div>`;
    const f = d.fuel || {};
    document.getElementById('brief-fuel').innerHTML = `
      <div class="brief-row"><span class="brief-label">⛽ Benzin</span><span class="brief-val">${f.benzin||'—'} ₺/L</span></div>
      <div class="brief-row"><span class="brief-label">🛢 Motorin</span><span class="brief-val">${f.motorin||'—'} ₺/L</span></div>
      <div class="brief-row"><span class="brief-label">🔥 LPG</span><span class="brief-val">${f.lpg||'—'} ₺/L</span></div>`;
    const news = d.headlines || [];
    document.getElementById('brief-news').innerHTML = news.length
      ? news.map(h=>`<div class="brief-row" style="display:block;font-size:.78rem">• ${h}</div>`).join('')
      : '<div style="color:var(--text-sub)">Yüklenemedi.</div>';
  } catch(e) { console.error(e); }
}
async function sendBriefingNow() {
  const r = await fetch('/briefing/send', {method:'POST'});
  alert((await r.json()).ok ? '✓ Telegram\'a gönderildi!' : 'Hata!');
}

// ══ WEB PUSH ══
async function enableNotifications() {
  if (!('Notification' in window)) { alert('Desteklenmiyor.'); return; }
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') { alert('İzin verilmedi.'); return; }
  try {
    const d = await (await fetch('/push/vapid_public')).json();
    if (!d.key) { alert('VAPID anahtarı ayarlanmamış.'); return; }
    const sw  = await navigator.serviceWorker.ready;
    const sub = await sw.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64(d.key)
    });
    await fetch('/push/subscribe', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(sub)
    });
    document.querySelector('[onclick="enableNotifications()"]').classList.add('active');
    alert('✓ Bildirimler etkinleştirildi!');
  } catch(e) { alert('Hata: '+e.message); }
}
function urlB64(b) {
  const p = '='.repeat((4-b.length%4)%4);
  const s = (b+p).replace(/-/g,'+').replace(/_/g,'/');
  return Uint8Array.from([...window.atob(s)].map(c=>c.charCodeAt(0)));
}

// ══ PWA ══
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredPrompt = e;
  document.getElementById('install-bar').style.display = 'flex';
});
function installPWA() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  deferredPrompt.userChoice.then(() => {
    deferredPrompt = null;
    document.getElementById('install-bar').style.display = 'none';
  });
}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
</script>
</body>
</html>"""

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return HTML

@app.route("/manifest.json")
def manifest(): return Response(MANIFEST, mimetype="application/manifest+json")

@app.route("/icon.svg")
def icon(): return Response(ICON_SVG, mimetype="image/svg+xml")

@app.route("/sw.js")
def sw(): return Response(SW_JS, mimetype="application/javascript")

@app.route("/chat_file", methods=["POST"])
def chat_file():
    """Dosya içeren mesajları HTTP üzerinden al, WebSocket'e yayınla."""
    text    = request.form.get("message","").strip() or "Bu dosyayı analiz et."
    mode    = request.form.get("mode","auto")
    session = request.form.get("session","default")
    file    = request.files.get("file")

    file_data = None
    if file and file.filename:
        fname = secure_filename(file.filename)
        if Path(fname).suffix.lower() in ALLOWED_EXT:
            save_path = UPLOAD_FOLDER / fname
            file.save(str(save_path))
            file_data = prepare_file(save_path, fname)

    # Kullanıcı mesajını kaydet ve yayınla
    msg_id = save_message("user", f"[{file.filename}] {text}" if file else text,
                          source="web", session=session)
    broadcast_message({
        "id": msg_id, "role": "user",
        "content": f"[{file.filename}] {text}" if file else text,
        "source": "web", "session": session,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }, session)

    threading.Thread(
        target=get_reply_and_broadcast,
        args=(text, mode, session, "web", file_data),
        daemon=True
    ).start()
    return jsonify({"ok": True})

@app.route("/session/clear", methods=["POST"])
def session_clear():
    data = request.get_json(force=True)
    clear_session(data.get("session","default"))
    return jsonify({"ok": True})

@app.route("/nc/data")
def nc_data():
    if not nc: return jsonify({"events":[],"notes":[],"tasks":[]})
    return jsonify({
        "events": [{"title":e.get("title",""),
                    "start":nc.format_event_time(e.get("start",""))}
                   for e in nc.get_today_events()[:5]],
        "notes":  [{"id":n["id"],"title":n["title"],"content":n["content"][:100]}
                   for n in nc.get_notes()[:5]],
        "tasks":  [{"title":t["title"],"due":t.get("due","")}
                   for t in nc.get_tasks()[:5]]
    })

@app.route("/nc/add_event", methods=["POST"])
def nc_add_event():
    if not nc: return jsonify({"ok":False})
    data = request.get_json(force=True)
    try:
        dt = datetime.datetime.strptime(data["datetime"], "%Y-%m-%d %H:%M")
        return jsonify({"ok": nc.add_event(data["title"], dt)})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/nc/add_note", methods=["POST"])
def nc_add_note():
    if not nc: return jsonify({"ok":False})
    data = request.get_json(force=True)
    return jsonify({"ok": nc.create_note(data.get("title","Not"),
                                          data.get("content",""), "JARVIS")})

@app.route("/briefing/data")
def briefing_data():
    return jsonify({"rates": get_exchange_rates(),
                    "fuel":  get_fuel_prices(),
                    "headlines": get_news_headlines(7)})

@app.route("/briefing/send", methods=["POST"])
def briefing_send():
    try:
        msg = run_briefing(nc_client=nc)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/push/vapid_public")
def push_vapid():
    return jsonify({"key": VAPID_PUBLIC})

@app.route("/push/subscribe", methods=["POST"])
def push_subscribe():
    sub = request.get_json(force=True)
    if sub not in _push_subscribers:
        _push_subscribers.append(sub)
    return jsonify({"ok":True})

if __name__ == "__main__":
    port = int(os.environ.get("JARVIS_PORT", WEB_PORT))
    try: local_ip = socket.gethostbyname(socket.gethostname())
    except: local_ip = "127.0.0.1"
    print("="*55)
    print("  ⬡  J.A.R.V.I.S. WebSocket Sunucusu")
    print("="*55)
    print(f"  Yerel:     http://localhost:{port}")
    print(f"  Ağ:        http://{local_ip}:{port}")
    print(f"  LM Studio: {LM_STUDIO_URL}")
    print(f"  Nextcloud: {NC_URL or 'Ayarlanmamış'}")
    print("="*55)
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
