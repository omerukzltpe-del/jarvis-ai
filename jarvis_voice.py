#!/usr/bin/env python3
"""
J.A.R.V.I.S. Voice Mode
- Boşluk tuşu basılı → mikrofon açık (push-to-talk)
- Whisper ile ses → metin
- Claude/Gemma ile yanıt
- pyttsx3/gTTS ile sesli yanıt
- Ekran görüntüsü + Claude Vision
- Sistem kontrolü (uygulama aç/kapat, dosya yönet)
- Küçük HUD penceresi
"""

import os, sys, time, threading, queue, subprocess, platform
import datetime, base64, json, io
from pathlib import Path

# GUI
import tkinter as tk
from tkinter import font as tkfont

# Ses
try:
    import sounddevice as sd
    import numpy as np
    SD_OK = True
except ImportError:
    SD_OK = False
    print("sounddevice kurulu değil: pip install sounddevice numpy")

try:
    import whisper
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False

try:
    import pyttsx3
    TTS_OK = True
except ImportError:
    TTS_OK = False

# Ekran görüntüsü
try:
    from PIL import ImageGrab, Image
    PIL_OK = True
except ImportError:
    try:
        import subprocess
        PIL_OK = False
    except Exception:
        PIL_OK = False

# Klavye dinleme
try:
    from pynput import keyboard
    PYNPUT_OK = True
except ImportError:
    PYNPUT_OK = False
    print("pynput kurulu değil: pip install pynput")

# AI
import anthropic, openai
sys.path.insert(0, str(Path(__file__).parent))
from jarvis_config import *
from jarvis_engine import AgentEngine
from jarvis_db import save_message, get_ai_history

# ── Sabitler ─────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 16000
WHISPER_MODEL  = "base"
SESSION        = "voice"
MAX_RECORD_SEC = 30    # max kayıt süresi

# ── Global durum ──────────────────────────────────────────────────────────────
engine       = AgentEngine()
whisper_mdl  = None
tts_engine   = None
audio_frames = []
is_recording = False
is_speaking  = False
audio_queue  = queue.Queue()


# ── Whisper ───────────────────────────────────────────────────────────────────
def load_whisper():
    global whisper_mdl
    if not WHISPER_OK:
        return
    print(f"Whisper yükleniyor ({WHISPER_MODEL})...")
    whisper_mdl = whisper.load_model(WHISPER_MODEL)
    print("Whisper hazır.")


def transcribe(audio_np) -> str:
    if not whisper_mdl:
        return ""
    try:
        audio_f32 = audio_np.astype("float32") / 32768.0
        result    = whisper_mdl.transcribe(audio_f32, language="tr",
                                            fp16=False)
        return result["text"].strip()
    except Exception as e:
        print(f"Whisper hatası: {e}")
        return ""


# ── TTS ───────────────────────────────────────────────────────────────────────
def init_tts():
    global tts_engine
    if not TTS_OK:
        return
    try:
        tts_engine = pyttsx3.init()
        tts_engine.setProperty("rate", 160)
        tts_engine.setProperty("volume", 0.9)
        for v in tts_engine.getProperty("voices"):
            if "tr" in v.id.lower() or "turkish" in v.name.lower():
                tts_engine.setProperty("voice", v.id)
                break
    except Exception as e:
        print(f"TTS hatası: {e}")
        tts_engine = None


def speak(text: str, on_done=None):
    global is_speaking
    is_speaking = True

    def _run():
        global is_speaking
        try:
            clean = text[:500]
            if tts_engine:
                tts_engine.say(clean)
                tts_engine.runAndWait()
            else:
                # Fallback: espeak
                subprocess.run(["espeak", "-v", "tr", "-s", "150", clean],
                               capture_output=True)
        except Exception as e:
            print(f"TTS çalıştırma hatası: {e}")
        finally:
            is_speaking = False
            if on_done:
                on_done()

    threading.Thread(target=_run, daemon=True).start()


# ── Ekran görüntüsü ───────────────────────────────────────────────────────────
def take_screenshot() -> str | None:
    """Ekranın base64 PNG'sini döndür."""
    try:
        if PIL_OK:
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        else:
            # Linux fallback: scrot
            tmp = "/tmp/jarvis_screen.png"
            subprocess.run(["scrot", tmp], capture_output=True)
            if Path(tmp).exists():
                return base64.b64encode(Path(tmp).read_bytes()).decode()
    except Exception as e:
        print(f"Screenshot hatası: {e}")
    return None


# ── Sistem komutları ──────────────────────────────────────────────────────────
SCREEN_KEYWORDS = [
    "ekrana bak", "ekranı gör", "ekranı incele", "ne görüyorsun",
    "ekranda ne var", "bak bakalım", "screenshota bak"
]

APP_COMMANDS = {
    "firefox": ["firefox"],
    "chrome":  ["google-chrome", "chromium-browser", "chromium"],
    "terminal": ["gnome-terminal", "xterm", "konsole"],
    "dosyalar": ["nautilus", "thunar", "dolphin"],
    "vs code":  ["code"],
    "müzik":    ["rhythmbox", "spotify"],
    "hesap makinesi": ["gnome-calculator", "kcalc"],
}

def open_app(name: str) -> str:
    name_low = name.lower()
    for key, cmds in APP_COMMANDS.items():
        if key in name_low:
            for cmd in cmds:
                if subprocess.run(["which", cmd],
                                  capture_output=True).returncode == 0:
                    subprocess.Popen([cmd])
                    return f"{key.capitalize()} açıldı."
    return f"'{name}' uygulaması bulunamadı."


def run_safe_cmd(cmd: str) -> str:
    SAFE = {"ls","pwd","date","uptime","df","free","uname","whoami",
            "echo","cat","head","tail","ping","ip","hostname"}
    first = cmd.strip().split()[0] if cmd.strip() else ""
    if first not in SAFE:
        return f"Güvenlik: '{first}' onaysız çalıştırılamaz."
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=10)
        return r.stdout.strip() or r.stderr.strip() or "(çıktı yok)"
    except Exception as e:
        return str(e)


# ── AI Yanıt ──────────────────────────────────────────────────────────────────
def get_ai_response(text: str, hud: "JarvisHUD") -> str:
    """Metin + opsiyonel ekran görüntüsü ile AI yanıtı al."""
    hud.set_state("thinking")
    hist = get_ai_history(SESSION, 20)

    # Ekran görüntüsü gerekiyor mu?
    needs_screen = any(kw in text.lower() for kw in SCREEN_KEYWORDS)
    file_data    = None
    if needs_screen:
        hud.set_state("screenshot")
        b64 = take_screenshot()
        if b64:
            file_data = {"type": "image", "mime": "image/png",
                         "b64": b64, "name": "ekran.png"}
            hud.log("📸 Ekran görüntüsü alındı")

    # Sistem komutları
    low = text.lower()
    if any(k in low for k in ["aç ", "başlat ", "çalıştır "]):
        for key in APP_COMMANDS:
            if key in low:
                result = open_app(key)
                save_message("user",      text,   source="voice", session=SESSION)
                save_message("assistant", result, source="jarvis", session=SESSION)
                return result

    # AI'a gönder
    hist.append({"role": "user", "content": text})
    save_message("user", text, source="voice", session=SESSION)

    try:
        # Ekran varsa Claude kullan (vision destekler)
        if file_data:
            chosen = "claude"
        else:
            chosen = engine.route(text)

        reply = engine.chat(chosen, hist, file_data=file_data)
    except anthropic.AuthenticationError:
        reply = "Claude API anahtarı geçersiz."
    except openai.APIConnectionError:
        reply = "LM Studio bağlantısı yok."
    except Exception as e:
        reply = f"Hata: {str(e)[:100]}"

    save_message("assistant", reply, model=chosen,
                 source="jarvis", session=SESSION)
    return reply


# ── HUD Penceresi ─────────────────────────────────────────────────────────────
class JarvisHUD:
    """Küçük, her zaman üstte duran JARVIS arayüzü."""

    STATES = {
        "idle":       ("#00d4ff", "● HAZIR — BOŞLUK: konuş"),
        "listening":  ("#aa44ff", "◎ DİNLİYOR..."),
        "thinking":   ("#ffaa00", "◌ DÜŞÜNÜYOR..."),
        "speaking":   ("#00ff88", "◉ KONUŞUYOR"),
        "screenshot": ("#ff8800", "📸 EKRAN ALIYOR..."),
        "error":      ("#ff4444", "✗ HATA"),
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("JARVIS")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.overrideredirect(True)   # çerçevesiz
        self.root.configure(bg="#000810")
        self.root.geometry("420x220+20+20")

        self._state   = "idle"
        self._drag_x  = 0
        self._drag_y  = 0
        self._anim_t  = 0
        self._wave    = [0.0] * 32

        self._build_ui()
        self._animate()

        # Pencereyi sürüklenebilir yap
        self.root.bind("<ButtonPress-1>",   self._drag_start)
        self.root.bind("<B1-Motion>",       self._drag_move)

    def _build_ui(self):
        # Canvas — hologram yüz
        self.canvas = tk.Canvas(self.root, width=420, height=140,
                                bg="#000810", highlightthickness=0)
        self.canvas.pack(fill=tk.X)

        # Durum çubuğu
        self.state_var = tk.StringVar(value="● HAZIR — BOŞLUK: konuş")
        self.state_lbl = tk.Label(
            self.root, textvariable=self.state_var,
            font=("Courier", 10, "bold"), fg="#00d4ff", bg="#000810",
            pady=2)
        self.state_lbl.pack(fill=tk.X)

        # Son mesaj
        self.msg_var = tk.StringVar(value="J.A.R.V.I.S. hazır.")
        self.msg_lbl = tk.Label(
            self.root, textvariable=self.msg_var,
            font=("Courier", 9), fg="#004a6e", bg="#000810",
            wraplength=400, justify=tk.LEFT, padx=8)
        self.msg_lbl.pack(fill=tk.X)

        # Kapat butonu
        tk.Button(
            self.root, text="✕", font=("Courier", 8),
            bg="#000810", fg="#ff4444", relief=tk.FLAT,
            command=self.root.quit, cursor="hand2"
        ).place(x=400, y=2)

    def _drag_start(self, e):
        self._drag_x = e.x
        self._drag_y = e.y

    def _drag_move(self, e):
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def set_state(self, state: str):
        self._state = state
        col, txt = self.STATES.get(state, ("#00d4ff", state))
        self.state_var.set(txt)
        self.state_lbl.configure(fg=col)

    def log(self, text: str):
        short = text[:60] + ("..." if len(text) > 60 else "")
        self.msg_var.set(short)

    def _animate(self):
        self._anim_t  += 0.07
        ring           = (self._anim_t * 40) % 360
        cx, cy         = 210, 68

        # Dalga güncelle
        amp = (1.0 if self._state == "speaking" else
               0.5 if self._state == "listening" else
               0.3 if self._state == "thinking"  else 0.08)
        import math, random
        if self._state in ("speaking", "listening"):
            self._wave.insert(0, (random.random()*2-1) * amp)
        else:
            self._wave.insert(0, math.sin(self._anim_t*3) * amp)
        self._wave.pop()

        c = self.canvas
        c.delete("all")

        # Grid
        c.configure(bg="#000810")
        for y in range(0, 140, 10):
            c.create_line(0, y, 420, y, fill="#010c18", width=1)

        # Renk
        rc = ("#00ff88" if self._state == "speaking"  else
              "#aa44ff" if self._state == "listening"  else
              "#ffaa00" if self._state == "thinking"   else
              "#00d4ff")

        # Dönen elips halkası
        for i in range(0, 340, 6):
            a1 = math.radians(i + ring)
            a2 = math.radians(i + 5 + ring)
            c.create_line(
                cx + 115*math.cos(a1), cy + 20*math.sin(a1),
                cx + 115*math.cos(a2), cy + 20*math.sin(a2),
                fill=rc, width=1.5)

        # Dikey halka
        for i in range(0, 340, 6):
            a1 = math.radians(i - ring*0.6)
            a2 = math.radians(i + 5 - ring*0.6)
            c.create_line(
                cx + 22*math.cos(a1), cy + 115*math.sin(a1),
                cx + 22*math.cos(a2), cy + 115*math.sin(a2),
                fill="#003a5c", width=1)

        # Yüz çemberi
        fr = 53 + math.sin(self._anim_t*2)*2
        c.create_oval(cx-fr, cy-fr, cx+fr, cy+fr,
                      outline="#00d4ff", width=2)

        # Gözler
        blink = 2 if math.fabs(math.sin(self._anim_t*0.3)) > 0.97 else 9
        ey    = cy - 14
        for ex in [cx-19, cx+19]:
            c.create_oval(ex-13, ey-blink, ex+13, ey+blink,
                          outline="#00d4ff", width=2, fill="#001020")
            if blink > 3:
                c.create_oval(ex-6, ey-6, ex+6, ey+6, fill="#00aaff")
                c.create_oval(ex-3, ey-3, ex+3, ey+3, fill="#000820")
                c.create_oval(ex-6, ey-6, ex-3, ey-3, fill="#ffffff")

        # Kaşlar
        brow = ey - blink - 7
        off  = 3 if self._state == "thinking" else 0
        c.create_line(cx-32, brow+off, cx-7,  brow,   fill="#00d4ff", width=2)
        c.create_line(cx+7,  brow,     cx+32, brow+off, fill="#00d4ff", width=2)

        # Ağız
        my  = cy + 24
        mw  = 28
        spk = self._state == "speaking"
        oh  = int(abs(math.sin(self._anim_t*8)) * 11) if spk else 0
        if oh > 2:
            c.create_arc(cx-mw, my-oh, cx+mw, my+oh,
                         start=0, extent=-180,
                         outline="#00d4ff", width=2, style=tk.ARC,
                         fill="#001020")
        else:
            c.create_line(cx-mw, my, cx+mw, my, fill="#00d4ff", width=2)

        # Ses dalgası
        wy  = cy + 55
        ww  = 100
        wamp = (16 if self._state=="speaking" else
                12 if self._state=="listening" else
                6  if self._state=="thinking"  else 2)
        wc   = rc
        pts  = []
        n    = len(self._wave)
        for i, v in enumerate(self._wave):
            x = cx - ww + (2*ww*i/(n-1))
            y = wy + v * wamp
            pts.extend([x, y])
        if len(pts) >= 4:
            c.create_line(pts, fill=wc, width=2, smooth=True)
        c.create_rectangle(cx-ww-2, wy-18, cx+ww+2, wy+18,
                           outline="#001a2a", width=1)

        # HUD köşe metinleri
        now = datetime.datetime.now().strftime("%H:%M:%S")
        c.create_text(4, 4,    anchor=tk.NW, text=f"SYS {now}",
                      font=("Courier",7), fill="#003a5c")
        c.create_text(416, 4,  anchor=tk.NE, text="J.A.R.V.I.S v3.0",
                      font=("Courier",7), fill="#003a5c")
        c.create_text(4, 130,  anchor=tk.SW, text="VOICE MODE",
                      font=("Courier",7), fill="#003a5c")
        c.create_text(416,130, anchor=tk.SE, text="RTX 3060",
                      font=("Courier",7), fill="#003a5c")

        self.root.after(30, self._animate)


# ── Push-to-Talk Motor ────────────────────────────────────────────────────────
class VoiceEngine:
    def __init__(self, hud: JarvisHUD):
        self.hud          = hud
        self.is_recording = False
        self.frames       = []
        self.stream       = None
        self._lock        = threading.Lock()

    def start_recording(self):
        if self.is_recording or not SD_OK:
            return
        with self._lock:
            self.is_recording = True
            self.frames       = []
        self.hud.set_state("listening")
        self.hud.log("🎤 Dinliyorum...")

        def callback(indata, frame_count, time_info, status):
            if self.is_recording:
                self.frames.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1,
            dtype="int16", callback=callback)
        self.stream.start()

    def stop_recording(self):
        if not self.is_recording:
            return
        with self._lock:
            self.is_recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.frames:
            self.hud.set_state("idle")
            return

        audio_np = np.concatenate(self.frames, axis=0).flatten()
        threading.Thread(target=self._process, args=(audio_np,),
                         daemon=True).start()

    def _process(self, audio_np):
        import numpy as np
        # Sessizlik kontrolü
        rms = np.sqrt(np.mean(audio_np.astype(float)**2))
        if rms < 200:
            self.hud.log("🔇 Ses algılanamadı")
            self.hud.set_state("idle")
            return

        # Whisper ile metne çevir
        self.hud.set_state("thinking")
        self.hud.log("⏳ Ses işleniyor...")
        text = transcribe(audio_np)
        if not text:
            self.hud.log("❌ Anlaşılamadı")
            self.hud.set_state("idle")
            return

        self.hud.log(f"🗣 {text}")

        # AI yanıtı al
        reply = get_ai_response(text, self.hud)
        self.hud.log(f"🤖 {reply[:80]}...")

        # Sesli yanıt ver
        self.hud.set_state("speaking")
        speak(reply, on_done=lambda: self.hud.set_state("idle"))


# ── Klavye Dinleyici ──────────────────────────────────────────────────────────
def setup_keyboard(voice_engine: VoiceEngine):
    if not PYNPUT_OK:
        print("⚠️ pynput yok — klavye dinleme devre dışı")
        return None

    def on_press(key):
        try:
            if key == keyboard.Key.space and not voice_engine.is_recording:
                voice_engine.start_recording()
        except Exception:
            pass

    def on_release(key):
        try:
            if key == keyboard.Key.space and voice_engine.is_recording:
                voice_engine.stop_recording()
            elif key == keyboard.Key.esc:
                return False   # Dinleyiciyi durdur
        except Exception:
            pass

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    return listener


# ── Ana Fonksiyon ─────────────────────────────────────────────────────────────
def main():
    print("⬡ J.A.R.V.I.S. Voice Mode başlatılıyor...")

    # TTS ve Whisper'ı arka planda yükle
    init_tts()
    threading.Thread(target=load_whisper, daemon=True).start()

    # HUD
    hud          = JarvisHUD()
    voice_engine = VoiceEngine(hud)

    # Klavye
    listener = setup_keyboard(voice_engine)
    if not listener:
        hud.log("⚠️ Klavye desteği yok — pip install pynput")

    hud.log("HAZIR — Boşluk tuşuna basılı tutarak konuşun")
    speak("J.A.R.V.I.S. ses modu aktif. Boşluk tuşuna basılı tutarak konuşabilirsiniz.")

    print("✅ JARVIS Voice aktif!")
    print("   BOŞLUK  → bas ve konuş, bırak → JARVIS cevaplar")
    print("   ESC     → çıkış")
    print()

    hud.root.mainloop()

    if listener:
        listener.stop()


if __name__ == "__main__":
    main()
