"""
J.A.R.V.I.S. — Sohbet Veritabanı
SQLite ile kalıcı, tüm cihazlarda senkron sohbet geçmişi
"""

import sqlite3
import json
import datetime
from pathlib import Path
import threading

DB_PATH = Path.home() / ".jarvis_chat.db"
_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            session   TEXT    NOT NULL DEFAULT 'default',
            role      TEXT    NOT NULL,  -- user | assistant | system
            content   TEXT    NOT NULL,
            model     TEXT    DEFAULT '',
            source    TEXT    DEFAULT 'web',  -- web | telegram | desktop
            timestamp TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_session ON messages(session);
        CREATE INDEX IF NOT EXISTS idx_ts      ON messages(timestamp);

        CREATE TABLE IF NOT EXISTS sessions (
            id        TEXT PRIMARY KEY,
            title     TEXT DEFAULT 'Sohbet',
            created   TEXT NOT NULL,
            updated   TEXT NOT NULL
        );
        """)
        conn.commit()
        conn.close()


def save_message(role: str, content: str, model: str = "",
                 source: str = "web", session: str = "default") -> int:
    ts = datetime.datetime.now().isoformat()
    with _lock:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO messages (session,role,content,model,source,timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (session, role, content, model, source, ts)
        )
        msg_id = cur.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id,title,created,updated) VALUES (?,?,?,?)",
            (session, "Sohbet", ts, ts)
        )
        conn.execute("UPDATE sessions SET updated=? WHERE id=?", (ts, session))
        conn.commit()
        conn.close()
    return msg_id


def get_messages(session: str = "default", limit: int = 100) -> list[dict]:
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
            (session, limit)
        ).fetchall()
        conn.close()
    return [dict(r) for r in reversed(rows)]


def get_ai_history(session: str = "default", limit: int = 40) -> list[dict]:
    """AI API için sadece user/assistant mesajları."""
    msgs = get_messages(session, limit * 2)
    return [{"role": m["role"], "content": m["content"]}
            for m in msgs if m["role"] in ("user", "assistant")][-limit:]


def get_sessions() -> list[dict]:
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY updated DESC LIMIT 20"
        ).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def clear_session(session: str = "default"):
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM messages WHERE session=?", (session,))
        conn.commit()
        conn.close()


def get_recent_message_count(session: str = "default") -> int:
    with _lock:
        conn = get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session=?", (session,)
        ).fetchone()[0]
        conn.close()
    return count


# Başlangıçta DB oluştur
init_db()
