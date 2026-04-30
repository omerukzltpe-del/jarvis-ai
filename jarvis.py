#!/usr/bin/env python3
"""
J.A.R.V.I.S. Masaüstü Uygulaması
Ubuntu + Windows uyumlu
Tailscale üzerinden LM Studio bağlantısı desteklenir
"""

import tkinter as tk
from tkinter import scrolledtext, ttk, filedialog
import threading, os, subprocess, platform
import datetime, webbrowser
from pathlib import Path

from jarvis_config import *
from jarvis_engine import AgentEngine, Memory, prepare_file

try:
    from jarvis_face import JarvisFace
    FACE_AVAILABLE = True
except ImportError:
    FACE_AVAILABLE = False

try:
    import speech_recognition as sr
    import sounddevice  # noqa
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False


class JarvisApp:
    def __init__(self, root):
        self.root = root
        self.root.title("J.A.R.V.I.S. — Multi-Agent AI")
        self.root.geometry("1000x760")
        self.root.configure(bg="#0a0e1a")
        self.root.resizable(True, True)

        self.engine  = AgentEngine()
        self.memory  = Memory()
        self.history = self.memory.load()
        self.is_listening  = False
        self._last_model   = "gemma"
        self._pending_file = None   # yüklenmeyi bekleyen dosya
        self.tts  = None
        self.face = None

        self._init_tts()
        self._build_ui()
        self._init_face()

        self.add_msg("SISTEM",
            f"J.A.R.V.I.S. Multi-Agent sistemi aktif.\n"
            f"LM Studio: {LM_STUDIO_URL}\n"
            f"💾 {self.memory.info(self.history)}", "system")
        self._speak("Sistemler hazır. Emrinizdeyim efendim.")

    # ── TTS ─────────────────────────────────────────────────────────────────
    def _init_tts(self):
        if not TTS_AVAILABLE:
            return
        try:
            self.tts = pyttsx3.init()
            self.tts.setProperty('rate', 155)
            for v in self.tts.getProperty('voices'):
                if 'tr' in v.id.lower() or 'turkish' in v.name.lower():
                    self.tts.setProperty('voice', v.id)
                    break
        except Exception:
            self.tts = None

    def _speak(self, text):
        if not self.tts:
            return
        clean = text
        for t in ['[WEB_SEARCH:', '[OPEN_FILE:', '[OPEN_FOLDER:']:
            if t in clean:
                clean = clean[:clean.index(t)]
        threading.Thread(target=self._speak_thread,
                         args=(clean[:350],), daemon=True).start()

    def _speak_thread(self, text):
        try:
            if self.face:
                self.face.set_speaking(True)
            self.tts.say(text)
            self.tts.runAndWait()
        except Exception:
            pass
        finally:
            if self.face:
                self.face.set_speaking(False)

    def _init_face(self):
        if FACE_AVAILABLE:
            self.face = JarvisFace(master=self.root)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Başlık
        hdr = tk.Frame(self.root, bg="#0a0e1a", pady=6)
        hdr.pack(fill=tk.X, padx=12)
        tk.Label(hdr, text="⬡  J.A.R.V.I.S.",
                 font=("Courier", 18, "bold"), fg="#00d4ff", bg="#0a0e1a").pack(side=tk.LEFT)
        tk.Label(hdr, text="  Multi-Agent AI",
                 font=("Courier", 10), fg="#004a6e", bg="#0a0e1a").pack(side=tk.LEFT)

        # Model seçici
        rgt = tk.Frame(hdr, bg="#0a0e1a")
        rgt.pack(side=tk.RIGHT)
        tk.Label(rgt, text="MODEL:", font=("Courier", 9),
                 fg="#004a6e", bg="#0a0e1a").pack(side=tk.LEFT, padx=(0, 4))
        self.model_var = tk.StringVar(value="⚡ OTO")
        self._combo_choices = [("⚡ OTO", "auto")] + \
                              [(MODELS[k]["name"], k) for k in MODELS]
        self.model_menu = ttk.Combobox(
            rgt, textvariable=self.model_var,
            values=[c[0] for c in self._combo_choices],
            width=16, state="readonly", font=("Courier", 9))
        self.model_menu.pack(side=tk.LEFT)
        self.model_menu.bind("<<ComboboxSelected>>", self._on_model_select)

        # Model durum paneli
        self.model_bar = tk.Frame(self.root, bg="#050810", pady=4)
        self.model_bar.pack(fill=tk.X, padx=12)
        self._build_model_bar()

        # Sohbet
        cf = tk.Frame(self.root, bg="#0a0e1a", padx=12, pady=4)
        cf.pack(fill=tk.BOTH, expand=True)
        self.chat = scrolledtext.ScrolledText(
            cf, wrap=tk.WORD, font=("Courier", 11),
            bg="#050810", fg="#00d4ff", insertbackground="#00d4ff",
            selectbackground="#003a5c", relief=tk.FLAT,
            state=tk.DISABLED, padx=10, pady=8)
        self.chat.pack(fill=tk.BOTH, expand=True)
        for k, m in MODELS.items():
            self.chat.tag_configure(k, foreground=m["color"], font=("Courier", 11))
        self.chat.tag_configure("user",   foreground="#ffffff", font=("Courier", 11))
        self.chat.tag_configure("system", foreground="#ffaa00", font=("Courier", 10, "italic"))
        self.chat.tag_configure("error",  foreground="#ff4444", font=("Courier", 10))
        self.chat.tag_configure("route",  foreground="#333333", font=("Courier", 9, "italic"))
        self.chat.tag_configure("file",   foreground="#00ff88", font=("Courier", 10, "italic"))

        # Durum
        self.status = tk.StringVar(value=f"● HAZIR  |  {LM_STUDIO_URL}")
        tk.Label(self.root, textvariable=self.status,
                 font=("Courier", 9), fg="#004a6e", bg="#050810",
                 anchor=tk.W, padx=10).pack(fill=tk.X)

        # Dosya alanı
        ff = tk.Frame(self.root, bg="#0a0e1a", padx=12, pady=3)
        ff.pack(fill=tk.X)
        self.file_btn = tk.Button(
            ff, text="📎 Dosya Ekle",
            bg="#001a0d", fg="#00ff88",
            font=("Courier", 9), relief=tk.FLAT,
            padx=8, pady=3, cursor="hand2",
            command=self._pick_file)
        self.file_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.file_lbl = tk.Label(
            ff, text="Resim, PDF, kod veya metin ekleyin",
            font=("Courier", 9), fg="#003a1a", bg="#0a0e1a")
        self.file_lbl.pack(side=tk.LEFT)
        self.file_clear_btn = tk.Button(
            ff, text="✕ Kaldır",
            bg="#1a0000", fg="#ff4444",
            font=("Courier", 9), relief=tk.FLAT,
            padx=6, pady=3, cursor="hand2",
            command=self._clear_file)
        # Başlangıçta gizli

        # Giriş
        inf = tk.Frame(self.root, bg="#0a0e1a", padx=12, pady=6)
        inf.pack(fill=tk.X)
        self.inp = tk.Entry(
            inf, font=("Courier", 12),
            bg="#050810", fg="#ffffff",
            insertbackground="#00d4ff", relief=tk.FLAT, bd=5)
        self.inp.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7, padx=(0, 8))
        self.inp.bind("<Return>", lambda e: self._send())

        bs = {"font": ("Courier", 10, "bold"), "relief": tk.FLAT,
              "padx": 10, "pady": 7, "cursor": "hand2"}
        self.send_btn = tk.Button(inf, text="GÖNDER",
                                  bg="#003a5c", fg="#00d4ff",
                                  command=self._send, **bs)
        self.send_btn.pack(side=tk.LEFT, padx=2)
        self.mic_btn = tk.Button(inf, text="🎙 DİNLE",
                                 bg="#1a0030", fg="#aa44ff",
                                 command=self._toggle_mic, **bs)
        self.mic_btn.pack(side=tk.LEFT, padx=2)

        # Hızlı butonlar
        qf = tk.Frame(self.root, bg="#0a0e1a", padx=12, pady=4)
        qf.pack(fill=tk.X)
        for lbl, cmd in [
            ("📁 Masaüstü",  lambda: self._quick("Masaüstünü aç")),
            ("🕐 Saat",      lambda: self._quick("Saat kaç?")),
            ("🌐 Haber",     lambda: self._quick("Bugünkü haberleri özetle")),
            ("🧮 Hesapla",   lambda: self._quick("2 üzeri 32 kaçtır?")),
            ("📄 Analiz",    lambda: self._quick("Bu dosyayı analiz et")),
            ("📋 Temizle",   self._clear),
        ]:
            tk.Button(qf, text=lbl, command=cmd,
                      bg="#0d1a2e", fg="#00d4ff",
                      font=("Courier", 9), relief=tk.FLAT,
                      padx=6, pady=3, cursor="hand2").pack(side=tk.LEFT, padx=2)

    def _build_model_bar(self):
        for w in self.model_bar.winfo_children():
            w.destroy()
        for k, m in MODELS.items():
            is_active = (k == self._last_model)
            bg = m["bg"] if is_active else "#050810"
            bc = m["color"] if is_active else "#111"
            f = tk.Frame(self.model_bar, bg=bg,
                         highlightbackground=bc, highlightthickness=1)
            f.pack(side=tk.LEFT, padx=3)
            tk.Label(f, text=m["name"], font=("Courier", 8, "bold"),
                     fg=m["color"], bg=bg, padx=6, pady=2).pack()
            tk.Label(f, text=m["desc"], font=("Courier", 7),
                     fg="#444", bg=bg, padx=6).pack()

    def _on_model_select(self, _=None):
        idx = self.model_menu.current()
        key = self._combo_choices[idx][1]
        self.engine.mode = key

    # ── DOSYA ───────────────────────────────────────────────────────────────
    def _pick_file(self):
        filetypes = [
            ("Desteklenen dosyalar",
             "*.jpg *.jpeg *.png *.gif *.webp *.pdf "
             "*.txt *.md *.py *.js *.ts *.json *.csv "
             "*.html *.css *.sh *.bat *.yaml *.yml"),
            ("Tüm dosyalar", "*.*")
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            p = Path(path)
            self._pending_file = p
            self.file_lbl.configure(
                text=f"📎 {p.name} ({p.stat().st_size//1024} KB)",
                fg="#00ff88")
            self.file_clear_btn.pack(side=tk.LEFT, padx=4)
            self.add_msg("SISTEM", f"Dosya eklendi: {p.name}", "file")

    def _clear_file(self):
        self._pending_file = None
        self.file_lbl.configure(
            text="Resim, PDF, kod veya metin ekleyin", fg="#003a1a")
        self.file_clear_btn.pack_forget()

    # ── MESAJLAŞMA ──────────────────────────────────────────────────────────
    def add_msg(self, sender, text, tag="gemma"):
        self.chat.configure(state=tk.NORMAL)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.chat.insert(tk.END, f"\n[{ts}] {sender}:\n", tag)
        self.chat.insert(tk.END, text + "\n", tag)
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _send(self):
        text = self.inp.get().strip()
        file = self._pending_file
        if not text and not file:
            return
        if not text:
            text = "Bu dosyayı analiz et ve içeriğini açıkla."
        self.inp.delete(0, tk.END)
        display = f"[{file.name}] {text}" if file else text
        self.add_msg("SİZ", display, "user")
        if file:
            self._clear_file()
        threading.Thread(
            target=self._respond, args=(text, file), daemon=True).start()

    def _quick(self, text):
        self.inp.delete(0, tk.END)
        self.inp.insert(0, text)
        self._send()

    def _respond(self, user_text: str, file_path=None):
        self.root.after(0, lambda: self.send_btn.configure(state=tk.DISABLED))
        if self.face:
            self.face.set_thinking(True)

        chosen = self.engine.route(user_text) \
            if self.engine.mode == "auto" else self.engine.mode
        self._last_model = chosen
        m = MODELS[chosen]

        if self.engine.mode == "auto":
            self.root.after(0, lambda: self.add_msg(
                "⚡ OTO", f"→ {m['name']} ({m['desc']})", "route"))

        self.root.after(0, lambda: self.status.set(
            f"● {m['name']} DÜŞÜNÜYOR..."))
        self.root.after(0, self._build_model_bar)

        ts = f"\n[{datetime.datetime.now().strftime('%d %B %Y, %H:%M')}]"
        self.history.append({"role": "user", "content": user_text + ts})

        # Dosya hazırla
        file_data = None
        if file_path:
            file_data = prepare_file(file_path, file_path.name)
            if file_data.get("type") == "unsupported":
                self.root.after(0, lambda: self.add_msg(
                    "SISTEM", f"Desteklenmeyen dosya türü: {file_path.suffix}", "error"))
                file_data = None

        prefix = f"JARVIS [{m['name']}]"

        try:
            if m["type"] in ("claude", "gemini"):
                reply = self.engine.chat(chosen, self.history,
                                         file_data=file_data)
                self.history.append({"role": "assistant", "content": reply})
                cmds = self._exec_cmds(reply)
                disp = reply
                for raw, done in cmds:
                    disp = disp.replace(raw, f"[✓ {done}]")
                self.root.after(0, lambda d=disp: self.add_msg(prefix, d, chosen))
            else:
                # LM Studio streaming
                # Dosyayı metne gömüyoruz
                if file_data and file_data.get("text"):
                    self.history[-1]["content"] = (
                        f"Şu dosyanın içeriğini analiz et [{file_data['name']}]:\n"
                        f"{file_data['text'][:4000]}\n\nSoru: {user_text}" + ts)

                self.root.after(0, lambda: self._stream_start(prefix, chosen))

                def on_chunk(d):
                    self.root.after(0,
                        lambda x=d: self._stream_append(x, chosen))

                reply = self.engine.chat(chosen, self.history,
                                          on_chunk=on_chunk)
                self.root.after(0, lambda: self.chat.configure(state=tk.NORMAL))
                self.root.after(0, lambda: self.chat.insert(tk.END, "\n"))
                self.root.after(0, lambda: self.chat.configure(state=tk.DISABLED))
                self.history.append({"role": "assistant", "content": reply})
                for raw, done in self._exec_cmds(reply):
                    self.root.after(0,
                        lambda d=done: self.add_msg("✓", d, "system"))

            self._speak(reply)
            self.memory.save(self.history)

        except Exception as e:
            import openai, anthropic
            err = str(e)
            if "APIConnectionError" in type(e).__name__:
                msg = (f"LM Studio bağlantısı yok!\n"
                       f"URL: {LM_STUDIO_URL}\n"
                       f"Windows'ta Local Server açık mı?")
            elif "AuthenticationError" in type(e).__name__:
                msg = "Claude API anahtarı geçersiz veya kredi bitti."
            else:
                msg = f"Hata: {err[:300]}"
            self.root.after(0, lambda m=msg: self.add_msg("HATA", m, "error"))

        if self.face:
            self.face.set_thinking(False)
        self.root.after(0, lambda: self.status.set(
            f"● HAZIR  |  {LM_STUDIO_URL}"))
        self.root.after(0, lambda: self.send_btn.configure(state=tk.NORMAL))
        self.root.after(0, self._build_model_bar)

    def _stream_start(self, prefix, tag):
        self.chat.configure(state=tk.NORMAL)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.chat.insert(tk.END, f"\n[{ts}] {prefix}:\n", tag)
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _stream_append(self, delta, tag):
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, delta, tag)
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    # ── KOMUTLAR ────────────────────────────────────────────────────────────
    def _exec_cmds(self, text):
        done = []
        try:
            if "[WEB_SEARCH:" in text:
                s = text.index("[WEB_SEARCH:") + 12
                e = text.index("]", s)
                q = text[s:e]
                webbrowser.open(f"https://www.google.com/search?q={q}")
                done.append((f"[WEB_SEARCH:{q}]", f"Arama: {q}"))
            if "[OPEN_FOLDER:" in text:
                s = text.index("[OPEN_FOLDER:") + 13
                e = text.index("]", s)
                p = os.path.expanduser(text[s:e])
                if platform.system() == "Windows":
                    os.startfile(p)
                elif platform.system() == "Darwin":
                    subprocess.run(["open", p])
                else:
                    subprocess.run(["xdg-open", p])
                done.append((f"[OPEN_FOLDER:{p}]", "Klasör açıldı"))
            if "[OPEN_FILE:" in text:
                s = text.index("[OPEN_FILE:") + 11
                e = text.index("]", s)
                p = text[s:e]
                if os.path.exists(p):
                    if platform.system() == "Windows":
                        os.startfile(p)
                    elif platform.system() == "Darwin":
                        subprocess.run(["open", p])
                    else:
                        subprocess.run(["xdg-open", p])
                    done.append((f"[OPEN_FILE:{p}]", "Dosya açıldı"))
        except Exception as ex:
            print(f"Komut hatası: {ex}")
        return done

    # ── MİKROFON ────────────────────────────────────────────────────────────
    def _toggle_mic(self):
        if not SR_AVAILABLE:
            self.add_msg("SISTEM",
                "Mikrofon için: pip install sounddevice SpeechRecognition",
                "error")
            return
        if self.is_listening:
            self.is_listening = False
            self.mic_btn.configure(text="🎙 DİNLE", bg="#1a0030")
            if self.face:
                self.face.set_listening(False)
        else:
            self.is_listening = True
            self.mic_btn.configure(text="⏹ DUR", bg="#300010")
            if self.face:
                self.face.set_listening(True)
            threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        r = sr.Recognizer()
        r.pause_threshold = 0.8
        try:
            with sr.Microphone() as src:
                self.root.after(0, lambda: self.add_msg(
                    "SISTEM", "Mikrofon aktif...", "system"))
                r.adjust_for_ambient_noise(src, duration=0.5)
                audio = r.listen(src, timeout=10, phrase_time_limit=15)
            text = r.recognize_google(audio, language="tr-TR")
            self.root.after(0, lambda: self.add_msg("SİZ (SES)", text, "user"))
            self.root.after(0, lambda: threading.Thread(
                target=self._respond, args=(text, None),
                daemon=True).start())
        except sr.WaitTimeoutError:
            self.root.after(0, lambda: self.add_msg(
                "SISTEM", "Ses algılanamadı.", "system"))
        except sr.UnknownValueError:
            self.root.after(0, lambda: self.add_msg(
                "SISTEM", "Anlaşılamadı.", "system"))
        except Exception as e:
            em = str(e)
            self.root.after(0, lambda m=em: self.add_msg("HATA", m, "error"))
        finally:
            self.is_listening = False
            self.root.after(0, lambda: self.mic_btn.configure(
                text="🎙 DİNLE", bg="#1a0030"))
            if self.face:
                self.face.set_listening(False)

    # ── TEMİZLE ─────────────────────────────────────────────────────────────
    def _clear(self):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete(1.0, tk.END)
        self.chat.configure(state=tk.DISABLED)
        self.history.clear()
        self.memory.clear()
        self.add_msg("SISTEM", "Sohbet ve hafıza temizlendi.", "system")


if __name__ == "__main__":
    root = tk.Tk()
    JarvisApp(root)
    root.mainloop()
