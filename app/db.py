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


# Columns added after the first release, migrated in place on older databases (fixed strings only).
USER_COLUMNS = (
    ("session_version", "INTEGER NOT NULL DEFAULT 0"),
    ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("disabled", "INTEGER NOT NULL DEFAULT 0"),
    ("use_global_ai", "INTEGER NOT NULL DEFAULT 1"),
    ("oidc_iss", "TEXT"),
)


def init_shared(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY,
          username TEXT UNIQUE NOT NULL,
          display_name TEXT,
          password_hash TEXT,
          oidc_sub TEXT,
          oidc_iss TEXT,
          email TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          session_version INTEGER NOT NULL DEFAULT 0,
          is_admin INTEGER NOT NULL DEFAULT 0,
          disabled INTEGER NOT NULL DEFAULT 0,
          use_global_ai INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    for name, ddl in USER_COLUMNS:
        if name not in cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
    # One SSO identity is the pair (issuer, subject). A NULL issuer (not yet stamped) counts as ''.
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_oidc_identity "
              "ON users(coalesce(oidc_iss, ''), oidc_sub) WHERE oidc_sub IS NOT NULL")
