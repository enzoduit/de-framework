"""
Feedback Database — shared SQLite store for human feedback on DE sessions.
Location: /var/de-agents/feedback.db  (shared across all DEs)
"""
import os
import sqlite3
from pathlib import Path


def _db_path() -> Path:
    return Path(os.environ.get('AGENTS_DIR', '/var/de-agents')) / 'feedback.db'


def init_db():
    """Create tables if they don't exist. Call once at server startup."""
    conn = sqlite3.connect(str(_db_path()))
    conn.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            de_name TEXT NOT NULL,
            session_id TEXT,
            session_summary TEXT,
            raw_text TEXT NOT NULL,
            proposed_changes TEXT,
            applied INTEGER DEFAULT 0,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            de_name TEXT NOT NULL,
            session_id TEXT NOT NULL UNIQUE,
            summary TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    conn.commit()
    conn.close()


def store_feedback(de_name: str, session_id: str = None,
                   session_summary: str = None, raw_text: str = '') -> int:
    """Insert a new feedback row and return its auto-incremented id."""
    conn = sqlite3.connect(str(_db_path()))
    cur = conn.execute(
        'INSERT INTO feedback (de_name, session_id, session_summary, raw_text) '
        'VALUES (?, ?, ?, ?)',
        (de_name, session_id, session_summary, raw_text),
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def get_feedback(feedback_id: int) -> dict | None:
    """Return a single feedback row as dict, or None if not found."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM feedback WHERE id = ?', (feedback_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_applied(feedback_id: int, changes_json: str = None):
    """Mark feedback as applied=1. Optionally store the serialised changes."""
    conn = sqlite3.connect(str(_db_path()))
    conn.execute(
        'UPDATE feedback SET applied = 1, '
        'proposed_changes = COALESCE(?, proposed_changes) WHERE id = ?',
        (changes_json, feedback_id),
    )
    conn.commit()
    conn.close()


def get_recent_feedback(de_name: str, limit: int = 5) -> list[dict]:
    """Return the most recent feedback rows for a DE as a list of dicts."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT * FROM feedback WHERE de_name = ? '
        'ORDER BY timestamp DESC LIMIT ?',
        (de_name, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Session Summary Cache ────────────────────────────────────────────────────

def get_summary(de_name: str, session_id: str) -> str | None:
    """Return cached LLM summary for a session, or None if not cached."""
    conn = sqlite3.connect(str(_db_path()))
    row = conn.execute(
        'SELECT summary FROM summaries WHERE de_name = ? AND session_id = ?',
        (de_name, session_id),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def store_summary(de_name: str, session_id: str, summary: str) -> None:
    """Store an LLM-generated summary for a session (upsert by session_id)."""
    conn = sqlite3.connect(str(_db_path()))
    conn.execute(
        'INSERT OR REPLACE INTO summaries (de_name, session_id, summary) '
        'VALUES (?, ?, ?)',
        (de_name, session_id, summary),
    )
    conn.commit()
    conn.close()
