import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "  chat_id TEXT PRIMARY KEY,"
            "  sheet_id TEXT,"
            "  email TEXT,"
            "  reg_state TEXT DEFAULT 'awaiting_sheet',"
            "  created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )


def get_user(chat_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None


def create_user(chat_id: str):
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (chat_id, reg_state) VALUES (?, 'awaiting_sheet')",
            (chat_id,),
        )


def set_sheet_id(chat_id: str, sheet_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET sheet_id = ?, reg_state = 'awaiting_email' WHERE chat_id = ?",
            (sheet_id, chat_id),
        )


def complete_registration(chat_id: str, email: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET email = ?, reg_state = 'complete' WHERE chat_id = ?",
            (email, chat_id),
        )
