import json
import logging
import sqlite3
from datetime import datetime

from claude_telegram_bot import config

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            cwd TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
    """)
    conn.commit()
    conn.close()


class SessionManager:
    """Manage per-user chat sessions with SQLite persistence."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._active_session_id: int | None = None

    # ── active session ──

    @property
    def active_session_id(self) -> int | None:
        if self._active_session_id is None:
            self._active_session_id = self._latest_session_id()
        return self._active_session_id

    def _latest_session_id(self) -> int | None:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id FROM sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
            (self.user_id,),
        ).fetchone()
        conn.close()
        return row["id"] if row else None

    def _make_session(self, name: str, cwd: str) -> int:
        now = datetime.utcnow().isoformat()
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO sessions (user_id, name, cwd, created_at, updated_at) VALUES (?,?,?,?,?)",
            (self.user_id, name, cwd, now, now),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid

    # ── public API ──

    def new_session(self, cwd: str = "") -> int:
        count = self._count_sessions()
        name = f"Session {count + 1}"
        sid = self._make_session(name, cwd)
        self._active_session_id = sid
        return sid

    def _count_sessions(self) -> int:
        conn = _get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE user_id=?", (self.user_id,)
        ).fetchone()
        conn.close()
        return row["cnt"]

    def switch_session(self, session_id: int) -> bool:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id FROM sessions WHERE id=? AND user_id=?",
            (session_id, self.user_id),
        ).fetchone()
        conn.close()
        if row:
            self._active_session_id = session_id
            return True
        return False

    def list_sessions(self) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, name, cwd, updated_at FROM sessions WHERE user_id=? ORDER BY updated_at DESC",
            (self.user_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_active_cwd(self) -> str:
        sid = self.active_session_id
        if sid is None:
            return ""
        conn = _get_conn()
        row = conn.execute("SELECT cwd FROM sessions WHERE id=?", (sid,)).fetchone()
        conn.close()
        return row["cwd"] if row else ""

    def set_cwd(self, cwd: str):
        sid = self.active_session_id
        if sid is None:
            return
        conn = _get_conn()
        conn.execute("UPDATE sessions SET cwd=?, updated_at=? WHERE id=?",
                      (cwd, datetime.utcnow().isoformat(), sid))
        conn.commit()
        conn.close()

    def add_message(self, role: str, content: str):
        sid = self.active_session_id
        if sid is None:
            sid = self.new_session()
        now = datetime.utcnow().isoformat()
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (sid, role, content, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (now, sid)
        )
        conn.commit()
        conn.close()

    def get_history(self, limit: int | None = None) -> list[dict]:
        limit = limit or config.MAX_HISTORY_MESSAGES
        sid = self.active_session_id
        if sid is None:
            return []
        conn = _get_conn()
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (sid, limit),
        ).fetchall()
        conn.close()
        return list(reversed([dict(r) for r in rows]))

    def build_prompt(self, user_message: str) -> str:
        """Build a prompt string that includes conversation history."""
        history = self.get_history()
        if not history:
            return user_message

        parts: list[str] = []
        for msg in history:
            if msg["role"] == "user":
                parts.append(f"User: {msg['content']}")
            elif msg["role"] == "assistant":
                parts.append(f"Assistant: {msg['content']}")
        parts.append(f"User: {user_message}")
        parts.append("Assistant:")
        return "\n\n".join(parts)
