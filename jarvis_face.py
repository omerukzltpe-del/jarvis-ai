#!/usr/bin/env python3
"""
J.A.R.V.I.S. Animasyonlu Yüz
- 3D dönen halka sistemi (hologram)
- Konuşurken ses dalgası animasyonu
- Göz + ağız animasyonu
- Pulse / nefes efekti
- jarvis.py ile entegre çalışır
"""

import tkinter as tk
import math
import time
import threading
import random

class JarvisFace:
    """
    Bağımsız animasyon penceresi.
    jarvis.py'den şu şekilde kullanılır:
        from jarvis_face import JarvisFace
        face = JarvisFace()
        face.set_speaking(True)   # konuşmaya başladığında
        face.set_speaking(False)  # bittiğinde
        face.set_thinking(True)   # AI cevap üretirken
    """

    def __init__(self, master=None):
        if master:
            self.win = tk.Toplevel(master)
        else:
            self.win = tk.Tk()

        self.win.title("J.A.R.V.I.S.")
        self.win.geometry("480x520")
        self.win.configure(bg="#000810")
        self.win.resizable(False, False)

        # Durum
        self.speaking  = False
        self.thinking  = False
        self.listening = False
        self._running  = True

        # Animasyon değişkenleri
        self.t         = 0.0       # zaman
        self.blink_t   = 0.0
        self.wave_pts  = [0.0] * 64
        self.mouth_open= 0.0
        self.ring_angle= 0.0
        self.pulse_r   = 0.0

        self.cx = 240   # merkez x
        self.cy = 240   # merkez y

        self.canvas = tk.Canvas(self.win, width=480, height=480,
                                bg="#000810", highlightthickness=0)
        self.canvas.pack()

        # Alt durum etiketi
        self.status_lbl = tk.Label(self.win, text="● HAZIR",
                                   font=("Courier", 10, "bold"),
                                   fg="#00d4ff", bg="#000810")
        self.status_lbl.pack(pady=4)

        # Animasyon döngüsü
        self._animate()

    # ── Dışarıdan çağrılan kontroller ───────────────────────────────────────
    def set_speaking(self, val: bool):
        self.speaking = val
        if val:
            self.status_lbl.configure(text="◉ KONUŞUYOR", fg="#00ffaa")
        else:
            self.status_lbl.configure(text="● HAZIR", fg="#00d4ff")

    def set_thinking(self, val: bool):
        self.thinking = val
        if val:
            self.status_lbl.configure(text="◌ DÜŞÜNÜYOR...", fg="#ffaa00")
        elif not self.speaking:
            self.status_lbl.configure(text="● HAZIR", fg="#00d4ff")

    def set_listening(self, val: bool):
        self.listening = val
        if val:
            self.status_lbl.configure(text="◎ DİNLİYOR", fg="#aa44ff")
        elif not self.speaking and not self.thinking:
            self.status_lbl.configure(text="● HAZIR", fg="#00d4ff")

    # ── Ana animasyon ────────────────────────────────────────────────────────
    def _animate(self):
        if not self._running:
            return
        self.t       += 0.04
        self.blink_t += 0.03
        self.ring_angle = (self.ring_angle + 1.5) % 360

        # Ses dalgası güncelle
        self._update_wave()

        # Ağız açıklığı
        if self.speaking:
            self.mouth_open = 0.5 + 0.5 * abs(math.sin(self.t * 8))
        else:
            self.mouth_open = max(0.0, self.mouth_open - 0.08)

        # Pulse
        if self.speaking:
            self.pulse_r = 12 + 10 * abs(math.sin(self.t * 6))
        elif self.thinking:
            self.pulse_r = 8 + 8 * abs(math.sin(self.t * 3))
        else:
            self.pulse_r = 4 + 4 * abs(math.sin(self.t * 1.5))

        self._draw()
        self.win.after(30, self._animate)   # ~33 FPS

    def _update_wave(self):
        n = len(self.wave_pts)
        for i in range(n - 1, 0, -1):
            self.wave_pts[i] = self.wave_pts[i-1] * 0.92
        if self.speaking:
            self.wave_pts[0] = random.uniform(-1, 1) * random.uniform(0.6, 1.0)
        elif self.thinking:
            self.wave_pts[0] = math.sin(self.t * 5) * 0.4
        else:
            self.wave_pts[0] = math.sin(self.t * 2) * 0.12

    # ── Çizim ────────────────────────────────────────────────────────────────
    def _draw(self):
        c = self.canvas
        c.delete("all")

        cx, cy = self.cx, self.cy

        # ── Arka plan ızgarası ──
        self._draw_grid(c)

        # ── Dış pulse halkası ──
        pr = 180 + self.pulse_r
        alpha_rings = [
            (pr + 20, "#001520"),
            (pr + 10, "#002535"),
            (pr,      "#003a50"),
        ]
        for r, col in alpha_rings:
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=col, width=1)

        # ── Dönen dış halkalar ──
        self._draw_rotating_rings(c, cx, cy)

        # ── Yüz çerçevesi ──
        face_r = 155
        c.create_oval(cx-face_r, cy-face_r, cx+face_r, cy+face_r,
                      outline="#00d4ff", width=2)
        c.create_oval(cx-face_r+4, cy-face_r+4, cx+face_r-4, cy+face_r-4,
                      outline="#004a6e", width=1)

        # ── Hologram tarama çizgileri ──
        self._draw_scanlines(c, cx, cy, face_r)

        # ── Gözler ──
        self._draw_eyes(c, cx, cy)

        # ── Burun ──
        c.create_line(cx, cy-10, cx-8, cy+15, cx+8, cy+15,
                      fill="#004a6e", width=1, smooth=True)

        # ── Ağız ──
        self._draw_mouth(c, cx, cy)

        # ── Ses dalgası ──
        self._draw_wave(c, cx, cy)

        # ── Köşe HUD elemanları ──
        self._draw_hud(c)

        # ── Merkez nokta ──
        c.create_oval(cx-3, cy-3, cx+3, cy+3, fill="#00ffff", outline="")

    def _draw_grid(self, c):
        for x in range(0, 480, 40):
            c.create_line(x, 0, x, 480, fill="#020d18", width=1)
        for y in range(0, 480, 40):
            c.create_line(0, y, 480, y, fill="#020d18", width=1)

    def _draw_scanlines(self, c, cx, cy, r):
        y = cy - r
        while y < cy + r:
            dx = math.sqrt(max(0, r*r - (y-cy)**2))
            c.create_line(cx-dx, y, cx+dx, y,
                          fill="#001a2a", width=1)
            y += 8

    def _draw_rotating_rings(self, c, cx, cy):
        rings = [
            (170, 2, "#00d4ff", 1.0),
            (165, 1, "#005580", 2.0),
            (175, 1, "#003355", -1.5),
        ]
        for r, w, col, speed in rings:
            a = math.radians(self.ring_angle * speed)
            # Elips efekti (3D görünüm)
            rx = r
            ry = r * 0.3
            # Dönen kesik halka
            for i in range(0, 340, 5):
                angle1 = math.radians(i + self.ring_angle * speed)
                angle2 = math.radians(i + 4 + self.ring_angle * speed)
                x1 = cx + rx * math.cos(angle1)
                y1 = cy + ry * math.sin(angle1)
                x2 = cx + rx * math.cos(angle2)
                y2 = cy + ry * math.sin(angle2)
                bright = int(128 + 127 * math.sin(angle1))
                c.create_line(x1, y1, x2, y2, fill=col, width=w)

        # İkinci eksen halkası
        r2 = 168
        for i in range(0, 340, 5):
            angle1 = math.radians(i + 90 + self.ring_angle * -0.8)
            angle2 = math.radians(i + 4 + 90 + self.ring_angle * -0.8)
            x1 = cx + r2 * 0.3 * math.cos(angle1)
            y1 = cy + r2 * math.sin(angle1)
            x2 = cx + r2 * 0.3 * math.cos(angle2)
            y2 = cy + r2 * math.sin(angle2)
            c.create_line(x1, y1, x2, y2, fill="#005580", width=1)

    def _draw_eyes(self, c, cx, cy):
        # Göz pozisyonları
        eye_y  = cy - 35
        eye_lx = cx - 45
        eye_rx = cx + 45
        eye_w  = 32
        eye_h  = 18

        # Göz kırpma
        blink = abs(math.sin(self.blink_t * 0.4))
        if blink > 0.97:  # Nadiren kırp
            blink_h = 2
        else:
            blink_h = eye_h

        for ex in [eye_lx, eye_rx]:
            # Dış parlama
            c.create_oval(ex-eye_w-4, eye_y-blink_h-4,
                          ex+eye_w+4, eye_y+blink_h+4,
                          outline="#003344", width=1, fill="")
            # Göz beyazı (mavi ton)
            c.create_oval(ex-eye_w, eye_y-blink_h,
                          ex+eye_w, eye_y+blink_h,
                          outline="#00d4ff", width=2, fill="#001525")
            # İris
            iris_r = min(10, blink_h - 2)
            if iris_r > 0:
                c.create_oval(ex-iris_r, eye_y-iris_r,
                              ex+iris_r, eye_y+iris_r,
                              fill="#00aaff", outline="#00ffff", width=1)
                # Pupil
                p = max(3, iris_r - 4)
                c.create_oval(ex-p, eye_y-p, ex+p, eye_y+p,
                              fill="#000820", outline="")
                # Parlama noktası
                c.create_oval(ex-p+2, eye_y-p+2,
                              ex-p+5, eye_y-p+5,
                              fill="#ffffff", outline="")

        # Kaşlar
        if self.thinking:
            # Düşünürken kaşlar çatılır
            c.create_line(eye_lx-eye_w, eye_y-blink_h-10,
                          eye_lx+eye_w, eye_y-blink_h-6,
                          fill="#00d4ff", width=2, smooth=True)
            c.create_line(eye_rx-eye_w, eye_y-blink_h-6,
                          eye_rx+eye_w, eye_y-blink_h-10,
                          fill="#00d4ff", width=2, smooth=True)
        else:
            c.create_line(eye_lx-eye_w, eye_y-blink_h-8,
                          eye_lx+eye_w, eye_y-blink_h-8,
                          fill="#00d4ff", width=2)
            c.create_line(eye_rx-eye_w, eye_y-blink_h-8,
                          eye_rx+eye_w, eye_y-blink_h-8,
                          fill="#00d4ff", width=2)

    def _draw_mouth(self, c, cx, cy):
        mouth_y = cy + 55
        mouth_w = 55
        open_h  = int(self.mouth_open * 20)

        if open_h > 2:
            # Açık ağız
            c.create_arc(cx-mouth_w, mouth_y-open_h,
                         cx+mouth_w, mouth_y+open_h,
                         start=0, extent=-180,
                         outline="#00d4ff", width=2, style=tk.ARC)
            # İç diş çizgisi
            c.create_line(cx-mouth_w+10, mouth_y,
                          cx+mouth_w-10, mouth_y,
                          fill="#004a6e", width=1)
            # Ses çizgileri ağız içinde
            for i in range(3):
                xi = cx - 20 + i * 20
                h = random.randint(2, open_h-2) if self.speaking else 2
                c.create_line(xi, mouth_y-h, xi, mouth_y+h,
                              fill="#00ffaa", width=2)
        else:
            # Kapalı ağız — düz çizgi
            c.create_line(cx-mouth_w, mouth_y,
                          cx+mouth_w, mouth_y,
                          fill="#00d4ff", width=2, smooth=True)
            # Köşe detayları
            c.create_line(cx-mouth_w, mouth_y,
                          cx-mouth_w+8, mouth_y+4,
                          fill="#004a6e", width=1)
            c.create_line(cx+mouth_w, mouth_y,
                          cx+mouth_w-8, mouth_y+4,
                          fill="#004a6e", width=1)

    def _draw_wave(self, c, cx, cy):
        """Alt ses dalgası"""
        wave_y  = cy + 105
        wave_w  = 130
        n       = len(self.wave_pts)
        amp     = 28 if self.speaking else (14 if self.thinking else 6)

        pts = []
        for i, v in enumerate(self.wave_pts):
            x = cx - wave_w + (2 * wave_w * i / (n - 1))
            y = wave_y + v * amp
            pts.extend([x, y])

        if len(pts) >= 4:
            # Gölge
            shadow = [p + 2 if i % 2 else p for i, p in enumerate(pts)]
            c.create_line(shadow, fill="#001a2a", width=3, smooth=True)
            # Ana dalga
            col = "#00ffaa" if self.speaking else ("#ffaa00" if self.thinking else "#00d4ff")
            c.create_line(pts, fill=col, width=2, smooth=True)

        # Dalga çerçevesi
        c.create_rectangle(cx-wave_w-5, wave_y-35,
                           cx+wave_w+5, wave_y+35,
                           outline="#002233", width=1)
        c.create_line(cx-wave_w-5, wave_y, cx+wave_w+5, wave_y,
                      fill="#001520", width=1, dash=(4, 4))

    def _draw_hud(self, c):
        """Köşe HUD bilgileri"""
        import datetime
        now = datetime.datetime.now()

        # Sol üst
        c.create_text(10, 10, anchor=tk.NW,
                      text=f"SYS: {now.strftime('%H:%M:%S')}",
                      font=("Courier", 8), fill="#004a6e")
        c.create_text(10, 24, anchor=tk.NW,
                      text="RTX 3060 ■■■■□",
                      font=("Courier", 8), fill="#004a6e")

        # Sağ üst
        mode = "SPEAKING" if self.speaking else ("THINKING" if self.thinking else "READY")
        c.create_text(470, 10, anchor=tk.NE,
                      text=f"MODE: {mode}",
                      font=("Courier", 8), fill="#004a6e")
        c.create_text(470, 24, anchor=tk.NE,
                      text="J.A.R.V.I.S v2.0",
                      font=("Courier", 8), fill="#004a6e")

        # Sol alt
        c.create_text(10, 460, anchor=tk.SW,
                      text="NEURAL: ACTIVE",
                      font=("Courier", 8), fill="#004a6e")

        # Sağ alt
        c.create_text(470, 460, anchor=tk.SE,
                      text="STARK INDUSTRIES",
                      font=("Courier", 8), fill="#004a6e")

        # Köşe dekorasyon çizgileri
        for x, y, dx, dy in [(0,0,1,1),(480,0,-1,1),(0,480,1,-1),(480,480,-1,-1)]:
            c.create_line(x, y, x+dx*40, y, fill="#00d4ff", width=1)
            c.create_line(x, y, x, y+dy*40, fill="#00d4ff", width=1)

    def mainloop(self):
        self.win.mainloop()

    def destroy(self):
        self._running = False
        self.win.destroy()


# ── Bağımsız test modu ───────────────────────────────────────────────────────
if __name__ == "__main__":
    face = JarvisFace()

    def demo():
        import time
        time.sleep(2)
        face.set_thinking(True)
        time.sleep(3)
        face.set_thinking(False)
        face.set_speaking(True)
        time.sleep(4)
        face.set_speaking(False)
        time.sleep(1)
        face.set_listening(True)
        time.sleep(3)
        face.set_listening(False)

    threading.Thread(target=demo, daemon=True).start()
    face.mainloop()
