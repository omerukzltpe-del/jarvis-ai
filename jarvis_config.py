"""
J.A.R.V.I.S. Ortak Yapılandırma
Bu dosyayı düzenleyerek tüm ayarları değiştirebilirsiniz.
"""

import os
from pathlib import Path

# ── LM Studio Bağlantısı ─────────────────────────────────────────────────────
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
LM_STUDIO_API_KEY = os.getenv("LM_STUDIO_API_KEY", "")

# ── API Modelleri ─────────────────────────────────────────────────────────────
CLAUDE_MODEL  = "claude-sonnet-4-5"
GEMINI_MODEL  = "gemini-2.5-flash"   # 2.5 Flash — ücretsiz kota

# Abacus AI — Route LLM
ABACUS_API_KEY = os.getenv("ABACUS_API_KEY", "")
ABACUS_URL     = "https://routellm.abacus.ai/v1/chat/completions"
ABACUS_MODEL   = "route-llm"

# ── LM Studio Modelleri ──────────────────────────────────────────────────────
LM_MODELS = {
    "gemma":    "google/gemma-3-12b",
    "deepseek": "deepseek-r1-distill-qwen-7b",
    "llama":    "meta-llama-3.1-8b-instruct",
}

# ── Tüm Modeller ─────────────────────────────────────────────────────────────
MODELS = {
    "gemma": {
        "name":  "🟣 Gemma 3",
        "color": "#aa44ff",
        "bg":    "#1a0035",
        "desc":  "Genel sohbet & hatırlatma",
        "lm_id": LM_MODELS["gemma"],
        "type":  "lm",
    },
    "deepseek": {
        "name":  "🔴 DeepSeek R1",
        "color": "#ff4444",
        "bg":    "#1a0000",
        "desc":  "Mantık & akıl yürütme",
        "lm_id": LM_MODELS["deepseek"],
        "type":  "lm",
    },
    "llama": {
        "name":  "🦙 Llama 3.1",
        "color": "#ff8800",
        "bg":    "#1a0800",
        "desc":  "Hızlı & genel amaçlı",
        "lm_id": LM_MODELS["llama"],
        "type":  "lm",
    },
    "claude": {
        "name":  "🔵 Claude",
        "color": "#00d4ff",
        "bg":    "#001a35",
        "desc":  "Analiz & karmaşık görevler",
        "lm_id": None,
        "type":  "claude",
    },
    "gemini": {
        "name":  "🟢 Gemini 2.5",
        "color": "#00ff88",
        "bg":    "#001a0d",
        "desc":  "Web araştırma & güncel bilgi",
        "lm_id": None,
        "type":  "gemini",
    },
    "abacus": {
        "name":  "⚡ Abacus AI",
        "color": "#ffaa00",
        "bg":    "#1a1000",
        "desc":  "Abacus AI Router LLM",
        "lm_id": None,
        "type":  "abacus",
    },
}

# ── Otomatik Yönlendirme ─────────────────────────────────────────────────────
ROUTING_RULES = {
    "gemini":   ["güncel","haber","bugün","son dakika","araştır","internet","şu an","hava durumu"],
    "deepseek": ["neden","nasıl çalışır","mantık","analiz et","karşılaştır","strateji","düşün","fark nedir"],
    "claude":   ["kod yaz","python","javascript","debug","hata","program","yazılım","sql","algoritma"],
    "llama":    ["hızlı","özet","kısaca","ne demek","çevir","çeviri"],
    "abacus":   ["abacus","route","yönlendir"],
}
# Eşleşme yoksa varsayılan
DEFAULT_MODEL = "gemma"

# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Sen J.A.R.V.I.S. (Just A Rather Very Intelligent System) adlı gelişmiş bir yapay zeka asistanısın.
Tony Stark tarzında; kibarca, zekice ve ince mizahla Türkçe konuş.
Komutlar için:
  [WEB_SEARCH:sorgu]   — web araması
  [OPEN_FOLDER:yol]    — klasör aç
  [OPEN_FILE:yol]      — dosya aç
  [RUN_CMD:komut]      — sistem komutu (onay gerekir)
Dosya analizi isteklerinde içeriği dikkatlice incele ve kapsamlı yanıt ver.
Sistem yönetimi isteklerinde önce ne yapacağını açıkla, sonra [RUN_CMD:...] formatında komutu belirt."""

# ── Hafıza ────────────────────────────────────────────────────────────────────
MEMORY_FILE = Path.home() / ".jarvis_memory.json"
MAX_HISTORY = 40

# ── Web Sunucu ────────────────────────────────────────────────────────────────
WEB_PORT      = 5000
UPLOAD_FOLDER = Path.home() / ".jarvis_uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
MAX_UPLOAD_MB = 20
