import json
import logging
import sqlite3
from pathlib import Path

from claude_telegram_bot import config

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            UNIQUE(user_id, name)
        )
    """)
    conn.commit()
    conn.close()


def add_project(user_id: int, name: str, path: str) -> tuple[bool, str]:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return False, f"Directory does not exist: {p}"
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO projects (user_id, name, path) VALUES (?,?,?)",
            (user_id, name, str(p)),
        )
        conn.commit()
        return True, f"Project '{name}' added ({p})"
    except sqlite3.IntegrityError:
        return False, f"Project '{name}' already exists. Use a different name."
    finally:
        conn.close()


def remove_project(user_id: int, name: str) -> tuple[bool, str]:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM projects WHERE user_id=? AND name=?",
        (user_id, name),
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    if deleted:
        return True, f"Project '{name}' removed."
    return False, f"Project '{name}' not found."


def list_projects(user_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT name, path FROM projects WHERE user_id=? ORDER BY name",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project_path(user_id: int, name: str) -> str | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT path FROM projects WHERE user_id=? AND name=?",
        (user_id, name),
    ).fetchone()
    conn.close()
    return row["path"] if row else None
