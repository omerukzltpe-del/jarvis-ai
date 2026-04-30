#!/usr/bin/env python3
"""
J.A.R.V.I.S. Telegram Botu
- Temiz arayüz, eski menüler yok
- Inline butonlarla model seçimi (OTO/Gemma/DeepSeek/Llama/Claude/Gemini/Abacus)
- Sesli mesaj gönder/al
- Sistem yönetimi onay mekanizması
- Web arayüzüyle sohbet senkronizasyonu
"""

import os, sys, asyncio, tempfile, datetime, subprocess, threading
import anthropic, openai

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                       BotCommand)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, filters, ContextTypes)

try:
    from gtts import gTTS
    TTS_OK = True
except ImportError:
    TTS_OK = False

try:
    import whisper
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False

from jarvis_config import *
from jarvis_engine import AgentEngine
from jarvis_db import save_message, get_ai_history, clear_session
from jarvis_system import (is_safe, is_forbidden, needs_approval,
                            run_command, get_system_info, parse_command_from_ai)

# ── Ayarlar ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
ALLOWED_USER_ID  = int(os.getenv("JARVIS_USER_ID", "0"))
JARVIS_WEB_URL   = os.getenv("JARVIS_WEB_URL", "http://localhost:5000")
DEFAULT_SESSION  = "default"
WHISPER_MODEL_S  = "base"

# ── Kullanıcı başına durum ────────────────────────────────────────────────────
user_modes:  dict[int, str]  = {}   # model seçimi (auto/gemma/...)
voice_on:    dict[int, bool] = {}   # sesli yanıt aç/kapat
# Onay bekleyen komutlar: {user_id: {"cmd": str, "msg_id": int}}
pending_cmds: dict[int, dict] = {}

engine      = AgentEngine()
whisper_mdl = None


def load_whisper():
    global whisper_mdl
    if not WHISPER_OK:
        return
    print(f"Whisper yükleniyor ({WHISPER_MODEL_S})...")
    whisper_mdl = whisper.load_model(WHISPER_MODEL_S)
    print("Whisper hazır.")


def is_allowed(uid: int) -> bool:
    return ALLOWED_USER_ID == 0 or uid == ALLOWED_USER_ID


# ── Model seçici klavye ───────────────────────────────────────────────────────
def model_keyboard(current: str = "auto") -> InlineKeyboardMarkup:
    model_rows = [
        [("⚡ OTO",        "auto"),    ("🟣 Gemma 3",   "gemma")],
        [("🔴 DeepSeek",   "deepseek"),("🦙 Llama 3.1", "llama")],
        [("🔵 Claude",     "claude"),  ("🟢 Gemini 2.5","gemini")],
        [("⚡ Abacus AI",  "abacus")],
    ]
    buttons = []
    for row in model_rows:
        btn_row = []
        for label, key in row:
            check = "✓ " if key == current else ""
            btn_row.append(InlineKeyboardButton(
                check + label, callback_data=f"model:{key}"))
        buttons.append(btn_row)
    return InlineKeyboardMarkup(buttons)


def approval_keyboard(cmd_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Onayla", callback_data=f"approve:{cmd_id}"),
        InlineKeyboardButton("❌ İptal",  callback_data=f"deny:{cmd_id}"),
    ]])


# ── Komut handler'ları ────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    current = user_modes.get(uid, "auto")
    await update.message.reply_text(
        "⬡ *J.A.R.V.I.S.* — Multi-Agent AI\n\n"
        "Metin veya 🎙 sesli mesaj gönderin.\n"
        "Aşağıdan model seçin veya OTO modda bırakın.\n\n"
        f"Sesli yanıt: {'✅' if voice_on.get(uid,True) else '❌'}",
        parse_mode="Markdown",
        reply_markup=model_keyboard(current)
    )


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid     = update.effective_user.id
    current = user_modes.get(uid, "auto")
    await update.message.reply_text(
        "🤖 *Model Seçin:*",
        parse_mode="Markdown",
        reply_markup=model_keyboard(current)
    )


async def cmd_ses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    voice_on[uid] = not voice_on.get(uid, True)
    durum = "✅ açık" if voice_on[uid] else "❌ kapalı"
    await update.message.reply_text(f"🔊 Sesli yanıt: {durum}")


async def cmd_sistem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("⏳ Sistem bilgisi alınıyor...")
    info = get_system_info()
    msg = (
        "💻 *Sistem Bilgisi*\n\n"
        f"🖥️ OS: `{info.get('os','—')}`\n"
        f"⏱ Uptime: `{info.get('uptime','—')}`\n"
        f"🧠 CPU: `{info.get('cpu','—').strip()}`\n"
        f"💾 RAM: `{info.get('memory','—')}`\n"
        f"💿 Disk: `{info.get('disk','—')}`\n"
        f"🌐 IP: `{info.get('ip','—')}`\n"
        f"⚙️ Servisler: `{info.get('services','—')} çalışıyor`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_takvim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    import requests as req
    try:
        r = req.get(f"{JARVIS_WEB_URL}/nc/data", timeout=8)
        d = r.json()
        events = d.get("events", [])
        if events:
            msg = "📅 *Bugünkü Etkinlikler:*\n" + "\n".join(
                f"• {e['start']} — {e['title']}" for e in events)
        else:
            msg = "📅 Bugün takvimde etkinlik yok."
    except Exception as e:
        msg = f"Takvim alınamadı: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_brifing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("⏳ Brifing hazırlanıyor...")
    import requests as req
    try:
        r = req.post(f"{JARVIS_WEB_URL}/briefing/send", timeout=30)
        d = r.json()
        if d.get("ok"):
            await update.message.reply_text("✅ Sabah brifing gönderildi!")
        else:
            await update.message.reply_text(f"Hata: {d.get('error','')}")
    except Exception as e:
        await update.message.reply_text(f"Brifing hatası: {e}")


async def cmd_temizle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    clear_session(f"tg-{uid}")
    clear_session(DEFAULT_SESSION)
    await update.message.reply_text("🗑 Sohbet geçmişi temizlendi.")


async def cmd_yardim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "⬡ *J.A.R.V.I.S. Komutları*\n\n"
        "/model — model seç\n"
        "/ses — sesli yanıtı aç/kapat\n"
        "/sistem — sistem bilgisi\n"
        "/takvim — bugünkü takvim\n"
        "/brifing — sabah brifingini gönder\n"
        "/temizle — sohbet geçmişini sil\n"
        "/yardim — bu mesaj\n\n"
        "💡 *Sesli mesaj* göndererek konuşabilirsiniz.\n"
        "📎 *Dosya* göndererek analiz yaptırabilirsiniz.",
        parse_mode="Markdown"
    )


# ── Callback: Model seçimi + Komut onayı ─────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    if data.startswith("model:"):
        key = data.split(":", 1)[1]
        user_modes[uid] = key
        engine.mode = key
        m = MODELS.get(key, {})
        name = m.get("name", key) if key != "auto" else "⚡ OTO"
        await query.edit_message_text(
            f"✅ Model: *{name}*\n"
            f"{'Otomatik yönlendirme aktif.' if key=='auto' else m.get('desc','')}",
            parse_mode="Markdown",
            reply_markup=model_keyboard(key)
        )

    elif data.startswith("approve:"):
        cmd_id = data.split(":", 1)[1]
        pending = pending_cmds.get(uid)
        if not pending or pending.get("id") != cmd_id:
            await query.edit_message_text("⚠️ Onay süresi geçti.")
            return
        cmd = pending["cmd"]
        await query.edit_message_text(f"⚙️ Çalıştırılıyor:\n`{cmd}`",
                                       parse_mode="Markdown")
        result = run_command(cmd, timeout=60)
        out = result["stdout"] or result["stderr"] or "(çıktı yok)"
        icon = "✅" if result["ok"] else "❌"
        await ctx.bot.send_message(
            uid,
            f"{icon} *Komut tamamlandı* (kod: {result['returncode']})\n"
            f"```\n{out[:3000]}\n```",
            parse_mode="Markdown"
        )
        del pending_cmds[uid]

    elif data.startswith("deny:"):
        pending_cmds.pop(uid, None)
        await query.edit_message_text("❌ Komut iptal edildi.")


# ── AI yanıtı ─────────────────────────────────────────────────────────────────
async def get_ai_reply(user_text: str, uid: int,
                       file_data: dict = None) -> tuple[str, str]:
    session = f"tg-{uid}"
    mode    = user_modes.get(uid, "auto")
    engine.mode = mode

    chosen  = engine.route(user_text)
    hist    = get_ai_history(session, 40)
    hist.append({"role": "user", "content": user_text})

    # Kullanıcı mesajını kaydet
    save_message("user", user_text, source="telegram", session=session)
    save_message("user", f"[Telegram] {user_text}",
                 source="telegram", session=DEFAULT_SESSION)

    loop = asyncio.get_event_loop()
    try:
        reply = await loop.run_in_executor(
            None, lambda: engine.chat(chosen, hist, file_data=file_data))
    except anthropic.AuthenticationError:
        reply  = "❌ Claude API anahtarı geçersiz."
        chosen = "error"
    except openai.APIConnectionError:
        reply  = f"❌ LM Studio bağlantısı yok!\nURL: {LM_STUDIO_URL}"
        chosen = "error"
    except Exception as e:
        reply  = f"❌ Hata: {str(e)[:200]}"
        chosen = "error"

    # Kaydet
    save_message("assistant", reply, model=chosen,
                 source="jarvis", session=session)
    save_message("assistant", reply, model=chosen,
                 source="jarvis", session=DEFAULT_SESSION)

    return reply, chosen


async def process_system_commands(reply: str, uid: int,
                                   ctx: ContextTypes.DEFAULT_TYPE) -> str:
    """AI yanıtındaki sistem komutlarını onay için sun."""
    commands = parse_command_from_ai(reply)
    if not commands:
        return reply

    import uuid
    for c in commands:
        if c["forbidden"]:
            await ctx.bot.send_message(
                uid, f"⛔ Bu komut yasak ve çalıştırılmayacak:\n`{c['cmd']}`",
                parse_mode="Markdown")
        elif c["safe"]:
            # Güvenli — direkt çalıştır
            result = run_command(c["cmd"])
            out = result["stdout"] or result["stderr"] or "(çıktı yok)"
            icon = "✅" if result["ok"] else "⚠️"
            await ctx.bot.send_message(
                uid,
                f"{icon} *Komut çalıştırıldı:*\n`{c['cmd']}`\n```\n{out[:2000]}\n```",
                parse_mode="Markdown")
        elif c["needs_approval"]:
            # Onay iste
            cmd_id = str(uuid.uuid4())[:8]
            pending_cmds[uid] = {"cmd": c["cmd"], "id": cmd_id}
            await ctx.bot.send_message(
                uid,
                f"⚠️ *Onay Gerekiyor*\n\nŞu komut çalıştırılmak isteniyor:\n"
                f"```\n{c['cmd']}\n```\nOnaylıyor musunuz?",
                parse_mode="Markdown",
                reply_markup=approval_keyboard(cmd_id))
    return reply


# ── Metin mesajı ──────────────────────────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    reply, chosen = await get_ai_reply(update.message.text, uid)

    m     = MODELS.get(chosen, {})
    label = m.get("name", "JARVIS")
    full  = f"{label}:\n{reply}" if chosen != "error" else reply
    await send_reply(update, ctx, full, reply)
    await process_system_commands(reply, uid, ctx)


# ── Sesli mesaj ───────────────────────────────────────────────────────────────
async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    await update.message.reply_text("🎙 Ses işleniyor...")

    voice = update.message.voice or update.message.audio
    vfile = await ctx.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await vfile.download_to_drive(tmp_path)

    wav_path = tmp_path.replace(".ogg", ".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", tmp_path, wav_path],
                       capture_output=True, check=True)
    except Exception:
        wav_path = tmp_path

    text = ""
    if whisper_mdl:
        loop = asyncio.get_event_loop()
        r    = await loop.run_in_executor(
            None, lambda: whisper_mdl.transcribe(wav_path, language="tr"))
        text = r["text"].strip()

    for p in [tmp_path, wav_path]:
        try:
            import os as _os; _os.unlink(p)
        except Exception:
            pass

    if not text:
        await update.message.reply_text("❌ Ses anlaşılamadı.")
        return

    await update.message.reply_text(f"📝 *Anladım:* {text}",
                                    parse_mode="Markdown")
    reply, chosen = await get_ai_reply(text, uid)
    m     = MODELS.get(chosen, {})
    label = m.get("name", "JARVIS")
    full  = f"{label}:\n{reply}" if chosen != "error" else reply
    await send_reply(update, ctx, full, reply)
    await process_system_commands(reply, uid, ctx)


async def send_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                     full_text: str, tts_text: str):
    """Metin + opsiyonel sesli yanıt gönder."""
    uid = update.effective_user.id
    # 4096 karakter sınırı
    for i in range(0, len(full_text), 4000):
        await update.message.reply_text(full_text[i:i+4000])

    if voice_on.get(uid, True) and TTS_OK:
        loop = asyncio.get_event_loop()
        def make_voice():
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            gTTS(text=tts_text[:500], lang="tr", slow=False).save(tmp.name)
            return tmp.name
        try:
            vpath = await loop.run_in_executor(None, make_voice)
            with open(vpath, "rb") as f:
                await ctx.bot.send_voice(update.effective_chat.id, f)
            import os as _os; _os.unlink(vpath)
        except Exception:
            pass


# ── Bot menüsünü ayarla ───────────────────────────────────────────────────────
async def post_init(app):
    """Bot başladığında komut menüsünü temizle ve yeniden ayarla."""
    commands = [
        BotCommand("model",   "🤖 Model seç"),
        BotCommand("ses",     "🔊 Sesli yanıtı aç/kapat"),
        BotCommand("sistem",  "💻 Sistem bilgisi"),
        BotCommand("takvim",  "📅 Bugünkü takvim"),
        BotCommand("brifing", "🌅 Sabah brifingini gönder"),
        BotCommand("temizle", "🗑 Sohbet geçmişini sil"),
        BotCommand("yardim",  "❓ Yardım"),
    ]
    await app.bot.set_my_commands(commands)
    print("✅ Bot komut menüsü güncellendi.")


# ── Ana fonksiyon ──────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        print("HATA: TELEGRAM_TOKEN ayarlanmamış!")
        sys.exit(1)

    if WHISPER_OK:
        threading.Thread(target=load_whisper, daemon=True).start()

    print("⬡ J.A.R.V.I.S. Telegram Botu başlatılıyor...")
    print(f"   Web URL:   {JARVIS_WEB_URL}")
    print(f"   LM Studio: {LM_STUDIO_URL}")
    print(f"   Abacus:    {ABACUS_URL}")

    app = (Application.builder()
           .token(TELEGRAM_TOKEN)
           .post_init(post_init)
           .build())

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("model",   cmd_model))
    app.add_handler(CommandHandler("ses",     cmd_ses))
    app.add_handler(CommandHandler("sistem",  cmd_sistem))
    app.add_handler(CommandHandler("takvim",  cmd_takvim))
    app.add_handler(CommandHandler("brifing", cmd_brifing))
    app.add_handler(CommandHandler("temizle", cmd_temizle))
    app.add_handler(CommandHandler("yardim",  cmd_yardim))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO, handle_voice))

    print("✅ Bot hazır! Telegram'dan /start yazın.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
