"""Live configuration store.

Settings an administrator may change at runtime live in the app_config table. Every read goes
through get(), which resolves: database value, else the matching environment variable, else the
built-in default. Nothing is cached, so a change applies to the next request.

Secrets (OIDC client secret, global Claude key, FDC key, personal Claude keys) are encrypted with
Fernet using a key derived from SECRET_KEY (HKDF-SHA256, fixed info string). Their plaintext is only
ever returned by get() / get_user_secret() for server-side use; APIs report {"set": bool} instead.
If SECRET_KEY changes, stored secrets cannot be decrypted and are treated as unset.

Environment-only settings (SECRET_KEY, DB_PATH, PUBLIC_URL, TRUST_PROXY, COOKIE_SECURE) are never
stored here: they are needed before the database is reachable or decide how cookies and client
addresses are trusted, so changing them needs a restart.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import db

log = logging.getLogger("macrolog.config")

HKDF_INFO = b"macrolog/secret-store/v1"
FALSE_WORDS = ("0", "false", "no", "off", "")
ENV_ONLY = ("SECRET_KEY", "DB_PATH", "PUBLIC_URL", "TRUST_PROXY", "COOKIE_SECURE")
TEST_RECORD_KEY = "_oidc_last_test"  # internal row, not a managed setting


@dataclass(frozen=True)
class Setting:
    env: str
    kind: str  # bool, str, url, int, price, secret
    default: str
    max_len: int = 256
    lo: float = 0
    hi: float = 0

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


MANAGED: dict[str, Setting] = {
    "local_login": Setting("LOCAL_LOGIN", "bool", "1"),
    "oidc_issuer": Setting("OIDC_ISSUER", "url", "", max_len=512),
    "oidc_client_id": Setting("OIDC_CLIENT_ID", "str", "", max_len=256),
    "oidc_client_secret": Setting("OIDC_CLIENT_SECRET", "secret", "", max_len=1024),
    "oidc_name": Setting("OIDC_NAME", "str", "", max_len=64),
    "oidc_allow_signup": Setting("OIDC_ALLOW_SIGNUP", "bool", "0"),
    "oidc_admin_group": Setting("OIDC_ADMIN_GROUP", "str", "", max_len=200),
    "oidc_user_group": Setting("OIDC_USER_GROUP", "str", "", max_len=200),
    "oidc_groups_claim": Setting("OIDC_GROUPS_CLAIM", "str", "groups", max_len=200),
    "ai_global_key": Setting("ANTHROPIC_API_KEY", "secret", "", max_len=512),
    "ai_model": Setting("AI_MODEL", "str", "", max_len=100),
    "ai_monthly_cap": Setting("AI_MONTHLY_REQUEST_CAP", "int", "100", lo=0, hi=100000),
    "ai_price_in_per_mtok": Setting("AI_PRICE_IN_PER_MTOK", "price", "", hi=10000),
    "ai_price_out_per_mtok": Setting("AI_PRICE_OUT_PER_MTOK", "price", "", hi=10000),
    # Server side switches for each Claude feature. On by default, so existing servers see no change.
    "ai_allow_label": Setting("AI_ALLOW_LABEL", "bool", "1"),
    "ai_allow_lookup": Setting("AI_ALLOW_LOOKUP", "bool", "1"),
    "ai_allow_recipe": Setting("AI_ALLOW_RECIPE", "bool", "1"),
    # Recipe import from a URL: the page is fetched by Anthropic's web fetch tool, never by this server. Off by default.
    "ai_allow_recipe_url": Setting("AI_ALLOW_RECIPE_URL", "bool", "0"),
    "ai_recipe_url_max_tokens": Setting("AI_RECIPE_URL_MAX_CONTENT_TOKENS", "int", "30000", lo=2000, hi=100000),
    "fdc_api_key": Setting("FDC_API_KEY", "secret", "DEMO_KEY", max_len=256),
    # Photos on foods and recipes (app/photos.py). Off by default; the size limit is the raw upload in MB.
    "allow_photos": Setting("ALLOW_PHOTOS", "bool", "0"),
    "photo_max_mb": Setting("PHOTO_MAX_MB", "int", "5", lo=1, hi=20),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_config(
  key TEXT PRIMARY KEY, value TEXT, secret INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_secrets(
  user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, value_enc TEXT NOT NULL,
  updated_at TEXT NOT NULL, PRIMARY KEY(user_id, name));
CREATE TABLE IF NOT EXISTS admin_log(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, admin_id INTEGER, action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
"""


class ConfigError(ValueError):
    """Invalid setting. The message never contains a secret value."""


def init(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit(c: sqlite3.Connection, actor_id: Optional[int], action: str, target: str, detail: str = "") -> None:
    """Append to admin_log. Callers must never pass secret values."""
    c.execute("INSERT INTO admin_log(at, admin_id, action, target, detail) VALUES (?,?,?,?,?)",
              (now_iso(), actor_id, action, target[:200], detail[:1000]))


# ---------------------------------------------------------------- encryption

def _fernet() -> Optional[Fernet]:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        return None
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=HKDF_INFO).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt(plaintext: str) -> str:
    f = _fernet()
    if f is None:
        raise ConfigError("SECRET_KEY is not set, so secrets cannot be stored")
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> Optional[str]:
    """Plaintext, or None when the token cannot be decrypted (SECRET_KEY changed or data damaged)."""
    f = _fernet()
    if f is None or not token:
        return None
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return None


_warned: set[str] = set()


def _warn_unreadable(name: str) -> None:
    if name not in _warned:
        _warned.add(name)
        log.warning("Stored secret '%s' could not be decrypted (was SECRET_KEY changed?). Treating it as unset.", name)


# ---------------------------------------------------------------- reading

def _row(key: str, c: Optional[sqlite3.Connection]) -> Optional[sqlite3.Row]:
    try:
        if c is not None:
            return c.execute("SELECT value, secret FROM app_config WHERE key=?", (key,)).fetchone()
        with db.conn() as own:
            return own.execute("SELECT value, secret FROM app_config WHERE key=?", (key,)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise


def _stored(key: str, c: Optional[sqlite3.Connection]) -> tuple[str, Optional[str], bool]:
    """(state, plaintext, unreadable). state is 'database' or 'none'."""
    row = _row(key, c)
    if row is None or row["value"] is None:
        return "none", None, False
    if not row["secret"] or row["value"] == "":
        return "database", row["value"], False
    plain = decrypt(row["value"])
    if plain is None:
        _warn_unreadable(key)
        return "none", None, True
    return "database", plain, False


def resolve(key: str, c: Optional[sqlite3.Connection] = None) -> tuple[str, str, bool]:
    """(value, source, unreadable). source is 'database', 'environment' or 'default'."""
    spec = MANAGED[key]
    state, value, unreadable = _stored(key, c)
    if state == "database":
        return value or "", "database", False
    if spec.env in os.environ:
        return os.environ[spec.env], "environment", unreadable
    return spec.default, "default", unreadable


_SPEC_DEFAULT = object()


def get(key: str, default: Any = _SPEC_DEFAULT, c: Optional[sqlite3.Connection] = None) -> Any:
    """DB value if present, else the environment variable, else default (the setting's own default)."""
    spec = MANAGED[key]
    state, value, _ = _stored(key, c)
    if state == "database":
        return value
    if spec.env in os.environ:
        return os.environ[spec.env]
    return spec.default if default is _SPEC_DEFAULT else default


def flag(key: str, c: Optional[sqlite3.Connection] = None) -> bool:
    return str(get(key, c=c)).strip().lower() not in FALSE_WORDS


def integer(key: str, c: Optional[sqlite3.Connection] = None) -> int:
    """Non-negative int, falling back to the setting's default when invalid."""
    default = int(MANAGED[key].default)
    try:
        n = int(get(key, c=c))
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


def price(key: str, c: Optional[sqlite3.Connection] = None) -> Optional[float]:
    try:
        v = float(str(get(key, c=c)).strip())
    except ValueError:
        return None
    return v if math.isfinite(v) and v >= 0 else None


def typed(key: str, c: Optional[sqlite3.Connection] = None) -> Any:
    kind = MANAGED[key].kind
    if kind == "bool":
        return flag(key, c)
    if kind == "int":
        return integer(key, c)
    if kind == "price":
        return price(key, c)
    return str(get(key, c=c))


def describe(c: Optional[sqlite3.Connection] = None) -> dict:
    """Every managed setting for the admin API. Secrets report only whether they are set."""
    out = {}
    for key, spec in MANAGED.items():
        value, source, unreadable = resolve(key, c)
        item: dict[str, Any] = {"source": source, "env": spec.env, "type": spec.kind}
        if spec.secret:
            item["set"] = source != "default" and bool(value.strip())
            item["unreadable"] = unreadable
        else:
            item["value"] = typed(key, c)
        out[key] = item
    return out


# ---------------------------------------------------------------- validation and writing

def _text(key: str, value: Any, spec: Setting) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    value = value.strip()
    if len(value) > spec.max_len:
        raise ConfigError(f"{key} must be at most {spec.max_len} characters")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ConfigError(f"{key} must not contain control characters")
    return value


def _url(key: str, value: Any, spec: Setting) -> str:
    value = _text(key, value, spec)
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or " " in value:
        raise ConfigError(f"{key} must be an http or https URL")
    if parts.username or parts.password or parts.fragment or parts.query:
        raise ConfigError(f"{key} must not contain credentials, a query or a fragment")
    return value


def _number(key: str, value: Any, spec: Setting, integral: bool) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{key} must be a number")
    if isinstance(value, str) and spec.kind == "price" and not value.strip():
        return ""  # explicitly unknown price
    try:
        num = float(value)
    except (ValueError, OverflowError):
        raise ConfigError(f"{key} must be a number") from None
    if not math.isfinite(num) or num < spec.lo or num > spec.hi:
        raise ConfigError(f"{key} must be between {spec.lo:g} and {spec.hi:g}")
    if integral:
        if num != int(num):
            raise ConfigError(f"{key} must be a whole number")
        return str(int(num))
    return repr(num) if num != int(num) else str(int(num))


def _boolean(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value in (0, 1) and not isinstance(value, float):
        return str(value)
    raise ConfigError(f"{key} must be true or false")


def _secret(key: str, value: Any, spec: Setting) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    value = value.strip()
    if not value:
        return ""
    if len(value) > spec.max_len or len(value) < 4:
        raise ConfigError(f"{key} must be 4 to {spec.max_len} characters")
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ConfigError(f"{key} must not contain spaces or control characters")
    return value


def validate(key: str, value: Any) -> Optional[str]:
    """Normalized string to store, or None to remove the override. Raises ConfigError."""
    if key in ENV_ONLY or key.upper() in ENV_ONLY:
        raise ConfigError(f"{key.upper()} is set in the environment (.env) and needs a restart to change")
    spec = MANAGED.get(key)
    if spec is None:
        raise ConfigError(f"Unknown setting '{key[:64]}'")
    if value is None:
        return None
    if spec.kind == "bool":
        return _boolean(key, value)
    if spec.kind == "int":
        return _number(key, value, spec, integral=True)
    if spec.kind == "price":
        return _number(key, value, spec, integral=False)
    if spec.kind == "url":
        return _url(key, value, spec)
    if spec.kind == "secret":
        return _secret(key, value, spec)
    return _text(key, value, spec)


def store(c: sqlite3.Connection, key: str, value: Optional[str]) -> None:
    """Write an already validated value. None deletes the override; secrets are encrypted."""
    if value is None:
        c.execute("DELETE FROM app_config WHERE key=?", (key,))
        return
    secret = MANAGED[key].secret
    stored = encrypt(value) if secret and value else value
    c.execute("INSERT INTO app_config(key, value, secret, updated_at) VALUES (?,?,?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value, secret=excluded.secret, "
              "updated_at=excluded.updated_at", (key, stored, 1 if secret else 0, now_iso()))


def unset(c: sqlite3.Connection, key: str) -> bool:
    if key not in MANAGED:
        raise ConfigError(f"Unknown setting '{key[:64]}'")
    return c.execute("DELETE FROM app_config WHERE key=?", (key,)).rowcount > 0


def get_internal(c: sqlite3.Connection, key: str) -> Optional[str]:
    row = _row(key, c)
    return row["value"] if row else None


def set_internal(c: sqlite3.Connection, key: str, value: Optional[str]) -> None:
    if value is None:
        c.execute("DELETE FROM app_config WHERE key=?", (key,))
        return
    c.execute("INSERT INTO app_config(key, value, secret, updated_at) VALUES (?,?,0,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
              (key, value, now_iso()))


# ---------------------------------------------------------------- per-user secrets

def _user_row(c: sqlite3.Connection, user_id: int, name: str) -> Optional[sqlite3.Row]:
    try:
        return c.execute("SELECT value_enc FROM user_secrets WHERE user_id=? AND name=?", (user_id, name)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise


def user_secret_state(c: sqlite3.Connection, user_id: int, name: str) -> str:
    """'set', 'unset' or 'unreadable'."""
    row = _user_row(c, user_id, name)
    if not row:
        return "unset"
    return "set" if decrypt(row["value_enc"]) is not None else "unreadable"


def get_user_secret(c: sqlite3.Connection, user_id: int, name: str) -> Optional[str]:
    row = _user_row(c, user_id, name)
    if not row:
        return None
    plain = decrypt(row["value_enc"])
    if plain is None:
        _warn_unreadable(f"user {user_id} {name}")
    return plain


def set_user_secret(c: sqlite3.Connection, user_id: int, name: str, value: str) -> None:
    c.execute("INSERT INTO user_secrets(user_id, name, value_enc, updated_at) VALUES (?,?,?,?) "
              "ON CONFLICT(user_id, name) DO UPDATE SET value_enc=excluded.value_enc, updated_at=excluded.updated_at",
              (user_id, name, encrypt(value), now_iso()))


def delete_user_secret(c: sqlite3.Connection, user_id: int, name: str) -> bool:
    return c.execute("DELETE FROM user_secrets WHERE user_id=? AND name=?", (user_id, name)).rowcount > 0
