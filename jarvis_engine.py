"""
J.A.R.V.I.S. — Ortak AI Motoru
Modeller: Gemma, DeepSeek, Llama (LM Studio) + Claude, Gemini, Abacus AI
"""

import os, json, shutil, subprocess, base64, datetime
from pathlib import Path
import anthropic, openai
from jarvis_config import *


class Memory:
    def load(self):
        try:
            if MEMORY_FILE.exists():
                d = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                return d.get("messages", [])[-MAX_HISTORY:]
        except Exception as e:
            print(f"Hafıza yüklenemedi: {e}")
        return []

    def save(self, messages):
        try:
            MEMORY_FILE.write_text(
                json.dumps({"messages": messages[-MAX_HISTORY:]},
                           ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Hafıza kaydedilemedi: {e}")

    def clear(self):
        try:
            MEMORY_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def info(self, messages):
        return f"{len(messages)} mesaj hafızada" if messages else "Hafıza boş"


class AgentEngine:
    def __init__(self):
        self.mode = "auto"
        self._claude  = None
        self._lm      = None

    @property
    def claude_client(self):
        if not self._claude:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                raise anthropic.AuthenticationError("ANTHROPIC_API_KEY ayarlanmamış")
            self._claude = anthropic.Anthropic(api_key=api_key)
        return self._claude

    @property
    def lm_client(self):
        if not self._lm:
            self._lm = openai.OpenAI(
                base_url=LM_STUDIO_URL,
                api_key=LM_STUDIO_API_KEY)
        return self._lm

    def route(self, text: str) -> str:
        if self.mode != "auto":
            return self.mode
        low = text.lower()
        for model, keywords in ROUTING_RULES.items():
            if any(kw in low for kw in keywords):
                return model
        return DEFAULT_MODEL

    def chat(self, model_key: str, history: list,
             on_chunk=None, file_data: dict = None) -> str:
        m = MODELS.get(model_key, MODELS[DEFAULT_MODEL])

        if m["type"] == "claude":
            return self._chat_claude(history, file_data)
        elif m["type"] == "gemini":
            last = history[-1]["content"] if history else ""
            return self._chat_gemini(last, file_data)
        elif m["type"] == "abacus":
            return self._chat_abacus(history, on_chunk)
        else:  # lm
            return self._chat_lm(m["lm_id"], history, on_chunk)

    # ── Claude ───────────────────────────────────────────────────────────────
    def _chat_claude(self, history: list, file_data: dict = None) -> str:
        messages = list(history)
        if file_data and messages:
            last = messages[-1]
            content = []
            if file_data["type"] == "image":
                content.append({
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": file_data["mime"],
                               "data": file_data["b64"]}
                })
            elif file_data["type"] in ("pdf", "text"):
                content.append({
                    "type": "text",
                    "text": f"[Dosya: {file_data['name']}]\n{file_data.get('text','')}"
                })
            content.append({"type": "text", "text": last["content"]})
            messages[-1] = {"role": "user", "content": content}

        r = self.claude_client.messages.create(
            model=CLAUDE_MODEL, max_tokens=2048,
            system=SYSTEM_PROMPT, messages=messages)
        return r.content[0].text

    # ── Gemini CLI ───────────────────────────────────────────────────────────
    def _chat_gemini(self, prompt: str, file_data: dict = None) -> str:
        g = shutil.which("gemini") or shutil.which("gemini-cli")
        if not g:
            return ("Gemini CLI kurulu değil.\n"
                    "npm install -g @google/gemini-cli && gemini auth login")

        full_prompt = prompt
        if file_data and file_data.get("text"):
            full_prompt = (f"[Dosya: {file_data['name']}]\n"
                           f"{file_data['text'][:4000]}\n\n{prompt}")

        for args in [
            [g, "-m", GEMINI_MODEL, "-p", full_prompt],
            [g, "--model", GEMINI_MODEL, "-p", full_prompt],
            [g, "-p", full_prompt],
        ]:
            try:
                r = subprocess.run(args, capture_output=True,
                                   text=True, timeout=60, encoding="utf-8")
                out = r.stdout.strip()
                if out:
                    return out
            except Exception:
                continue
        return "Gemini yanıt vermedi."

    # ── Abacus AI ────────────────────────────────────────────────────────────
    def _chat_abacus(self, history: list, on_chunk=None) -> str:
        import requests as req
        headers = {
            "Authorization": f"Bearer {ABACUS_API_KEY}",
            "Content-Type": "application/json"
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
        payload  = {
            "model":    ABACUS_MODEL,
            "messages": messages,
            "stream":   on_chunk is not None
        }
        try:
            if on_chunk:
                import json as _json
                response = req.post(ABACUS_URL, headers=headers,
                                    data=_json.dumps(payload),
                                    stream=True, timeout=60)
                full = ""
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            line = line[6:]
                            if line == "[DONE]":
                                break
                            try:
                                chunk = _json.loads(line)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    full += content
                                    on_chunk(content)
                            except Exception:
                                continue
                return full
            else:
                import json as _json
                response = req.post(ABACUS_URL, headers=headers,
                                    data=_json.dumps(payload), timeout=60)
                data = response.json()
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]
                return f"Abacus yanıt hatası: {data}"
        except Exception as e:
            return f"Abacus AI bağlantı hatası: {str(e)[:200]}"

    # ── LM Studio (Gemma / DeepSeek / Llama) ─────────────────────────────────
    def _chat_lm(self, model_id: str, history: list,
                 on_chunk=None) -> str:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + history
        try:
            if on_chunk:
                full = ""
                stream = self.lm_client.chat.completions.create(
                    model=model_id, messages=msgs,
                    max_tokens=1024, stream=True)
                for chunk in stream:
                    d = chunk.choices[0].delta.content or ""
                    full += d
                    on_chunk(d)
                return full
            else:
                r = self.lm_client.chat.completions.create(
                    model=model_id, messages=msgs, max_tokens=1024)
                return r.choices[0].message.content
        except openai.APIConnectionError:
            raise
        except Exception as e:
            if "model" in str(e).lower() or "404" in str(e):
                return (f"'{model_id}' LM Studio'da yüklü değil.\n"
                        f"LM Studio > Models bölümünden indirin.")
            raise


def prepare_file(file_path: Path, filename: str) -> dict:
    suffix = file_path.suffix.lower()
    try:
        if suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png",  ".gif": "image/gif",
                    ".webp": "image/webp"}.get(suffix, "image/jpeg")
            b64 = base64.standard_b64encode(file_path.read_bytes()).decode()
            return {"type": "image", "mime": mime, "b64": b64, "name": filename}
        elif suffix == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(file_path))
                text = "\n".join(p.extract_text() or "" for p in reader.pages)
                return {"type": "pdf", "text": text[:8000], "name": filename}
            except ImportError:
                return {"type": "pdf", "text": "[pypdf kurulu değil]", "name": filename}
        elif suffix in (".txt", ".md", ".py", ".js", ".ts", ".json", ".csv",
                        ".html", ".css", ".xml", ".yaml", ".yml", ".sh", ".bat"):
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return {"type": "text", "text": text[:8000], "name": filename}
        else:
            return {"type": "unsupported", "name": filename}
    except Exception as e:
        return {"type": "error", "name": filename, "error": str(e)}
