"""Shared SQLite helpers. Each module creates its own tables in an init(c) function."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager


def db_path() -> str:
    return os.environ.get("DB_PATH", "data/macrolog.db")


@contextmanager
def conn():
    path = db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_shared(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY,
          username TEXT UNIQUE NOT NULL,
          display_name TEXT,
          password_hash TEXT,
          oidc_sub TEXT UNIQUE,
          email TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          session_version INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "session_version" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
