"""Authentication: local username/password and OpenID Connect (authentik).

JSON routes live under /api/auth, browser redirect routes under /auth/oidc.
The session middleware is configured in main.py; this module only sets and
clears request.session["uid"] (plus a short lived "oidc" entry during login).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from pydantic import BaseModel, Field

from . import config, db, deps

log = logging.getLogger("macrolog.auth")

router = APIRouter()

# scrypt parameters for new hashes. Stored in every hash string, so they can be
# raised later without breaking existing passwords. n=2**15, r=8 uses 32 MiB.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 128 * 1024 * 1024
MIN_PASSWORD = 8
MAX_PASSWORD = 1024

# Login rate limit: failures counted in a sliding window, persisted in SQLite.
RATE_WINDOW = 15 * 60
RATE_MAX_USER = 5
RATE_MAX_IP = 20
# At most this many scrypt hashes run at once (each uses 32 MiB and a core).
SCRYPT_SLOTS = threading.Semaphore(4)

OIDC_FLOW_TTL = 10 * 60
CACHE_TTL = 60 * 60
ALLOWED_ALGS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
DISABLED_MESSAGE = "This account is disabled. Ask the administrator."
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,63}$")

PERSONAL_KEY = "anthropic"  # user_secrets name of the personal Claude key (shared with ai.py)

_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------- settings

def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def local_enabled() -> bool:
    return config.flag("local_login")


def normalize_issuer(issuer: str) -> str:
    issuer = (issuer or "").strip()
    return issuer if not issuer or issuer.endswith("/") else issuer + "/"


def oidc_issuer() -> str:
    return normalize_issuer(config.get("oidc_issuer"))


def current_issuer(c: sqlite3.Connection) -> str:
    return normalize_issuer(str(config.get("oidc_issuer", c=c)))


def oidc_client_id() -> str:
    return str(config.get("oidc_client_id")).strip()


def oidc_name() -> str:
    return str(config.get("oidc_name")).strip() or "authentik"


def oidc_enabled() -> bool:
    return bool(oidc_issuer() and oidc_client_id() and public_url())


def public_url() -> str:
    return os.environ.get("PUBLIC_URL", "").strip().rstrip("/")


def redirect_uri() -> str:
    return public_url() + "/auth/oidc/callback"


# ---------------------------------------------------------------- passwords

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """Return 'scrypt$n$r$p$salt$hash' with a fresh 16 byte salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Malformed or missing hashes never match."""
    try:
        algo, n, r, p, salt, expected = (stored or "").split("$")
        if algo != "scrypt":
            return False
        expected_b = base64.b64decode(expected)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                             p=int(p), maxmem=SCRYPT_MAXMEM, dklen=len(expected_b))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected_b)


_dummy: dict[tuple, str] = {}


def _dummy_hash() -> str:
    """A hash with current parameters, used so unknown users cost the same time."""
    key = (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    if key not in _dummy:
        _dummy[key] = hash_password(secrets.token_urlsafe(16))
    return _dummy[key]


def needs_rehash(stored: str) -> bool:
    return not stored.startswith(f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$")


# ---------------------------------------------------------------- users

def normalize_username(name: str) -> str:
    return (name or "").strip().lower()


def validate_username(name: str) -> str:
    name = normalize_username(name)
    if not USERNAME_RE.match(name):
        raise ValueError("Username must be 1 to 64 characters: letters, digits, '.', '_', '-', '@'")
    return name


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    if len(password) > MAX_PASSWORD:
        raise ValueError(f"Password must be at most {MAX_PASSWORD} characters")


def find_user(c: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM users WHERE lower(username)=?", (normalize_username(username),)).fetchone()


def public_user(row) -> dict:
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"]}


def create_user(c: sqlite3.Connection, username: str, password: str | None = None,
                display_name: str | None = None, email: str | None = None,
                password_hash: str | None = None, is_admin: bool = False) -> int:
    """Create a local user. Raises ValueError on invalid input or a taken name.
    Pass password_hash (from hash_password) to hash before taking a write lock."""
    name = validate_username(username)
    if password is not None:
        validate_password(password)
        password_hash = hash_password(password)
    if find_user(c, name):
        raise ValueError(f"User '{name}' already exists")
    if not is_admin and not c.execute("SELECT 1 FROM users WHERE is_admin=1 AND disabled=0 LIMIT 1").fetchone():
        is_admin = True  # a household with no active admin always promotes the next account created
    cur = c.execute(
        "INSERT INTO users(username, display_name, password_hash, email, is_admin) VALUES (?,?,?,?,?)",
        (name, (display_name or "").strip() or name, password_hash, (email or "").strip() or None,
         1 if is_admin else 0),
    )
    return cur.lastrowid


def user_count(c: sqlite3.Connection) -> int:
    return c.execute("SELECT count(*) FROM users").fetchone()[0]


def set_password(c: sqlite3.Connection, username: str, password: str) -> None:
    validate_password(password)
    row = find_user(c, username)
    if not row:
        raise ValueError(f"No user '{normalize_username(username)}'")
    c.execute("UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?",
              (hash_password(password), row["id"]))


def set_email(c: sqlite3.Connection, username: str, email: str) -> None:
    row = find_user(c, username)
    if not row:
        raise ValueError(f"No user '{normalize_username(username)}'")
    c.execute("UPDATE users SET email=? WHERE id=?", ((email or "").strip() or None, row["id"]))


def list_users(c: sqlite3.Connection) -> list[dict]:
    rows = c.execute(
        "SELECT id, username, display_name, email, created_at, password_hash IS NOT NULL AS has_password,"
        " oidc_sub IS NOT NULL AS has_oidc, is_admin, disabled FROM users ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- module API

def init(c: sqlite3.Connection) -> None:
    config.init(c)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS login_failures(
          key TEXT NOT NULL,
          at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS login_failures_key ON login_failures(key, at);
        """
    )
    pin_unstamped_identities(c, current_issuer(c))


def pin_unstamped_identities(c: sqlite3.Connection, issuer: str) -> None:
    """Stamp linked users that have no issuer yet with `issuer` (no-op when there is none)."""
    if issuer:
        c.execute("UPDATE users SET oidc_iss=? WHERE oidc_sub IS NOT NULL AND oidc_iss IS NULL", (issuer,))


def bootstrap_admin() -> None:
    """Create ADMIN_USER with ADMIN_PASSWORD when the users table is empty, mark ADMIN_USER as an
    administrator (only when that account has a password), and if no administrator exists at all, promote the lowest-id enabled user."""
    username = os.environ.get("ADMIN_USER", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    with db.conn() as c:
        db.init_shared(c)
        if username and password and not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            try:
                create_user(c, username, password)
                log.info("Created first user '%s' from ADMIN_USER", normalize_username(username))
            except ValueError as exc:
                log.error("ADMIN_USER not created: %s", exc)
        if username:
            c.execute("UPDATE users SET is_admin=1 WHERE lower(username)=? AND password_hash IS NOT NULL",
                      (normalize_username(username),))  # never promote an SSO-only account by name
        _ensure_an_admin(c)


def _ensure_an_admin(c: sqlite3.Connection) -> None:
    if c.execute("SELECT 1 FROM users WHERE is_admin=1 LIMIT 1").fetchone():
        return
    row = c.execute("SELECT id, username FROM users ORDER BY disabled, id LIMIT 1").fetchone()
    if row:
        c.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
        log.info("No administrator existed: made '%s' an administrator", row["username"])


def active_admin_count(c: sqlite3.Connection, exclude: int | None = None, sso_only: bool = False,
                       issuer: str | None = None, null_matches: bool = True) -> int:
    """Active administrators. With sso_only, only those linked to `issuer` (default: the configured one);
    an unstamped (NULL) issuer counts when null_matches, i.e. when `issuer` is the one in effect now."""
    sql = "SELECT count(*) FROM users WHERE is_admin=1 AND disabled=0 AND id IS NOT ?"
    args: list = [exclude]
    if sso_only:
        sql += " AND oidc_sub IS NOT NULL AND (oidc_iss = ?" + (" OR oidc_iss IS NULL)" if null_matches else ")")
        args.append(normalize_issuer(issuer) if issuer is not None else current_issuer(c))
    return c.execute(sql, args).fetchone()[0]


def set_admin(c: sqlite3.Connection, username: str, admin: bool) -> sqlite3.Row:
    """Grant or revoke administrator rights. Revoking the last active admin raises ValueError.
    Revoking also ends that user's sessions."""
    row = find_user(c, username)
    if not row:
        raise ValueError(f"No user '{normalize_username(username)}'")
    if admin:
        c.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
    elif row["is_admin"]:
        if not row["disabled"] and active_admin_count(c, exclude=row["id"]) == 0:
            raise ValueError("Refusing to remove the last active administrator")
        c.execute("UPDATE users SET is_admin=0, session_version=session_version+1 WHERE id=?", (row["id"],))
    return row


def set_disabled(c: sqlite3.Connection, username: str, disabled: bool) -> sqlite3.Row:
    row = find_user(c, username)
    if not row:
        raise ValueError(f"No user '{normalize_username(username)}'")
    if disabled and row["is_admin"] and not row["disabled"] and active_admin_count(c, exclude=row["id"]) == 0:
        raise ValueError("Refusing to disable the last active administrator")
    if disabled and not row["disabled"]:
        c.execute("UPDATE users SET disabled=1, session_version=session_version+1 WHERE id=?", (row["id"],))
    elif not disabled:
        c.execute("UPDATE users SET disabled=0 WHERE id=?", (row["id"],))
    return row


# ---------------------------------------------------------------- request helpers

def client_ip(request: Request) -> str:
    """Client address. X-Forwarded-For is trusted only with TRUST_PROXY=1, and
    then only its last entry (the one appended by our own reverse proxy)."""
    if _flag("TRUST_PROXY", "0"):
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def require_same_origin(request: Request) -> None:
    """Dependency for cookie-authenticated state-changing routes. Rejects
    requests whose Origin header is present and is not our own origin.
    Our origin is PUBLIC_URL when set, else the Host header."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(403, "Cross-origin request rejected")
    origin = request.headers.get("origin")
    if origin is None:
        return
    if public_url():
        ok = origin.lower() == _origin_of(public_url())
    else:
        ok = urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower()
    if not ok:
        raise HTTPException(403, "Cross-origin request rejected")


def safe_next(value: str | None) -> str:
    """Only same-origin relative paths are allowed as redirect targets."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if "\\" in value or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value


def _start_session(request: Request, uid: int) -> None:
    with db.conn() as c:
        row = c.execute("SELECT session_version FROM users WHERE id=?", (uid,)).fetchone()
    request.session.clear()
    request.session["uid"] = uid
    request.session["sv"] = row["session_version"] if row else 0


# ---------------------------------------------------------------- rate limit

def _failures(c: sqlite3.Connection, key: str, now: float) -> list[float]:
    rows = c.execute("SELECT at FROM login_failures WHERE key=? AND at>? ORDER BY at", (key, now - RATE_WINDOW))
    return [r["at"] for r in rows]


def _retry_after(c: sqlite3.Connection, keys: list[tuple[str, int]], now: float) -> int:
    """Seconds until allowed again, or 0 when no key is over its limit."""
    wait = 0
    for key, limit in keys:
        times = _failures(c, key, now)
        if len(times) >= limit:
            wait = max(wait, int(times[-limit] + RATE_WINDOW - now) + 1)
    return wait


def _reserve_attempt(keys: list[tuple[str, int]], now: float) -> tuple[int, list[int]]:
    """Atomically check the limits and, if allowed, insert one pending failure row per key.
    Returns (retry_after, row ids). BEGIN IMMEDIATE serializes parallel logins, so every
    attempt counts before its password is checked and a burst cannot exceed the limit."""
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        wait = _retry_after(c, keys, now)
        if wait:
            return wait, []
        c.execute("DELETE FROM login_failures WHERE at<=?", (now - RATE_WINDOW,))
        ids = [c.execute("INSERT INTO login_failures(key, at) VALUES (?,?)", (k, now)).lastrowid for k, _ in keys]
    return 0, ids


def _check_password(c: sqlite3.Connection, name: str, password: str):
    """Verify under the scrypt semaphore. Returns the user row on success, else None."""
    row = find_user(c, name)
    stored = row["password_hash"] if row and row["password_hash"] else None
    with SCRYPT_SLOTS:
        ok = verify_password(password, stored or _dummy_hash()) and stored is not None
        if ok and needs_rehash(stored):
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row["id"]))
    return row if ok else None


def _forgive(c: sqlite3.Connection, user_key: str, ids: list[int]) -> None:
    """Successful login: reset the username counter and drop this attempt's pending rows."""
    c.execute("DELETE FROM login_failures WHERE key=?", (user_key,))
    c.executemany("DELETE FROM login_failures WHERE rowid=?", [(i,) for i in ids])


# ---------------------------------------------------------------- local routes

class LoginBody(BaseModel):
    username: str = Field(max_length=256)
    password: str = Field(max_length=MAX_PASSWORD)


@router.get("/api/auth/config")
def public_config() -> dict:
    with db.conn() as c:
        mode = first_run_mode(c)
    return {"local": local_enabled(), "oidc": oidc_enabled(), "oidc_name": oidc_name(),
            "needs_setup": mode == "setup", "first_admin_via_sso": mode == "sso"}


@router.post("/api/auth/login", dependencies=[Depends(require_same_origin)])
def login(body: LoginBody, request: Request):
    if not local_enabled():
        raise HTTPException(404, "Password login is disabled on this server")
    name = normalize_username(body.username)
    keys = [("user:" + name, RATE_MAX_USER), ("ip:" + client_ip(request), RATE_MAX_IP)]
    wait, ids = _reserve_attempt(keys, time.time())
    if wait:
        minutes = max(1, (wait + 59) // 60)
        return JSONResponse({"detail": f"Too many sign-in attempts. Try again in {minutes} minute(s)."},
                            status_code=429, headers={"Retry-After": str(wait)})
    with db.conn() as c:
        row = _check_password(c, name, body.password)
        if row and not row["disabled"]:
            _forgive(c, keys[0][0], ids)
    if not row:
        log.info("Failed password sign-in from %s", keys[1][0][3:])
        raise HTTPException(401, "Wrong username or password")
    if row["disabled"]:
        log.info("Refused password sign-in for disabled user '%s'", row["username"])
        raise HTTPException(403, DISABLED_MESSAGE)
    _start_session(request, row["id"])
    return public_user(row)


@router.post("/api/auth/logout", dependencies=[Depends(require_same_origin)])
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


SETUP_MAX_IP = 10
SETUP_DONE = "Setup is already complete. Sign in instead."
SETUP_VIA_SSO = "Password sign-in is off. Sign in with SSO to create the first admin"
SETUP_FIRST = "Finish first-run setup first"


def first_run_mode(c: sqlite3.Connection) -> str:
    """'' when users exist, 'sso' when the first admin must come from SSO (password sign-in off and SSO
    configured), else 'setup' (the setup screen creates the first admin)."""
    if user_count(c):
        return ""
    return "sso" if not config.flag("local_login", c) and oidc_enabled() else "setup"


def _setup_fields(body) -> tuple[str, str, str]:
    """(username, display_name, password) from a hand-parsed body, so errors never echo the password."""
    if not isinstance(body, dict) or set(body) - {"username", "display_name", "password"}:
        raise HTTPException(400, 'Send {"username", "password", "display_name"?}')
    name, password, display = body.get("username"), body.get("password"), body.get("display_name")
    if not isinstance(name, str) or not isinstance(password, str):
        raise HTTPException(400, "username and password are required")
    if display is not None and (not isinstance(display, str) or len(display.strip()) > 100
                                or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in display)):
        raise HTTPException(400, "display_name must be at most 100 characters without control characters")
    try:
        name = validate_username(name)
        validate_password(password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    display = " ".join((display or "").split())
    return name, display, password


@router.post("/api/auth/setup", dependencies=[Depends(require_same_origin)])
def setup(request: Request, body: Any = Body(None)):
    """Create the first administrator. Only while the users table is empty; 409 forever after."""
    with db.conn() as c:
        mode = first_run_mode(c)
    if not mode:
        raise HTTPException(409, SETUP_DONE)
    if mode == "sso":
        raise HTTPException(409, SETUP_VIA_SSO)
    wait, _ = _reserve_attempt([("setup:" + client_ip(request), SETUP_MAX_IP)], time.time())
    if wait:
        return JSONResponse({"detail": "Too many setup attempts. Try again later."}, status_code=429,
                            headers={"Retry-After": str(wait)})
    name, display, password = _setup_fields(body)
    with SCRYPT_SLOTS:
        pw_hash = hash_password(password)  # outside the write lock
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if user_count(c):  # re-check under the lock: exactly one caller can win
            raise HTTPException(409, SETUP_DONE)
        uid = create_user(c, name, display_name=display, password_hash=pw_hash, is_admin=True)
        config.audit(c, uid, "setup.first_admin", f"{name} (id {uid})")
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    log.info("First-run setup created administrator '%s'", name)
    _start_session(request, uid)
    return {**public_user(row), "is_admin": True}


@router.post("/api/auth/sso/unlink", dependencies=[Depends(require_same_origin)])
def sso_unlink(user: dict = Depends(deps.current_user)) -> dict:
    """Remove the current user's SSO link. Only while they can still sign in with a password."""
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT oidc_sub, password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row["oidc_sub"]:
            raise HTTPException(409, "Your account is not linked to single sign-on.")
        if not row["password_hash"]:
            raise HTTPException(409, "Your account has no password, so unlinking would lock you out. "
                                     "Ask the administrator to set a password first.")
        if not config.flag("local_login", c):
            raise HTTPException(409, "Password sign-in is off on this server, so unlinking would lock you out.")
        c.execute("UPDATE users SET oidc_sub=NULL, oidc_iss=NULL WHERE id=?", (user["id"],))
        config.audit(c, user["id"], "self.sso_unlink", f"{user['username']} (id {user['id']})")
    log.info("User %s unlinked single sign-on", user["id"])
    return me(user)


@router.get("/api/auth/me")
def me(user: dict = Depends(deps.current_user)) -> dict:
    with db.conn() as c:
        row = c.execute("SELECT use_global_ai, oidc_sub, password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        key_state = config.user_secret_state(c, user["id"], PERSONAL_KEY)
    return {**user, "use_global_ai": bool(row and row["use_global_ai"]), "personal_key_set": key_state == "set",
            "sso_linked": bool(row and row["oidc_sub"]), "has_password": bool(row and row["password_hash"])}


# ---------------------------------------------------------------- OIDC helpers

class OIDCError(Exception):
    """Sign-in failure with a message safe to show the user."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _http() -> httpx.AsyncClient:
    """HTTP client for the provider. Tests replace this with a mock transport."""
    return httpx.AsyncClient(timeout=10, headers={"User-Agent": "macrolog/0.1"})


async def _get_json(url: str) -> dict:
    try:
        async with _http() as client:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("OIDC provider request failed: %s %s", url, type(exc).__name__)
        raise OIDCError("The sign-in provider could not be reached. Try again later.", 502) from exc


async def _cached(url: str, refresh: bool = False) -> dict:
    hit = _cache.get(url)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    data = await _get_json(url)
    _cache[url] = (time.time(), data)
    return data


async def discovery() -> dict:
    issuer = oidc_issuer()
    meta = await _cached(issuer + ".well-known/openid-configuration")
    if meta.get("issuer") != issuer:
        log.error("OIDC discovery issuer %r does not match OIDC_ISSUER %r", meta.get("issuer"), issuer)
        raise OIDCError("Sign-in provider is misconfigured (issuer mismatch).", 502)
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not meta.get(field):
            raise OIDCError(f"Sign-in provider is misconfigured (missing {field}).", 502)
    return meta


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def _exchange_code(meta: dict, code: str, verifier: str) -> dict:
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": oidc_client_id(), "code_verifier": verifier}
    secret = config.get("oidc_client_secret")
    if secret:
        form["client_secret"] = secret
    try:
        async with _http() as client:
            resp = await client.post(meta["token_endpoint"], data=form, headers={"Accept": "application/json"})
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("OIDC token request failed: %s", type(exc).__name__)
        raise OIDCError("The sign-in provider could not be reached. Try again later.", 502) from exc
    if resp.status_code != 200 or not data.get("id_token"):
        log.warning("OIDC token endpoint returned %s error=%s", resp.status_code, data.get("error"))
        raise OIDCError("The sign-in provider rejected the login. Please try again.")
    return data


def _verify_signature(id_token: str, keys: dict) -> dict | None:
    try:
        return jwt.decode(id_token, KeySet.import_key_set(keys), algorithms=ALLOWED_ALGS).claims
    except (JoseError, ValueError, KeyError, TypeError) as exc:
        log.warning("OIDC id_token signature check failed: %s", type(exc).__name__)
        return None


async def _decode_id_token(meta: dict, id_token: str) -> dict:
    url = meta["jwks_uri"]
    claims = _verify_signature(id_token, await _cached(url))
    fetched_at = _cache.get(url, (0.0, {}))[0]
    if claims is None and time.time() - fetched_at > 60:
        # Keys may have rotated: refetch the JWKS (at most once a minute) and retry.
        claims = _verify_signature(id_token, await _cached(url, refresh=True))
    if claims is None:
        raise OIDCError("Sign-in failed: the identity token could not be verified.")
    return claims


def _validate_claims(claims: dict, issuer: str, nonce: str) -> None:
    client_id = oidc_client_id()
    registry = jwt.JWTClaimsRegistry(
        leeway=60,
        iss={"essential": True, "value": issuer},
        aud={"essential": True, "value": client_id},
        exp={"essential": True},
        sub={"essential": True},
        nonce={"essential": True, "value": nonce},
    )
    try:
        registry.validate(claims)
    except JoseError as exc:
        log.warning("OIDC id_token claim check failed: %s", exc.error)
        raise OIDCError("Sign-in failed: the identity token is invalid or expired. Please try again.") from exc
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != client_id:
        raise OIDCError("Sign-in failed: the identity token was issued for another application.")


async def _userinfo(meta: dict, tokens: dict, claims: dict) -> dict:
    """Fill in profile claims from the userinfo endpoint if the id_token lacks them."""
    if "email" in claims and "preferred_username" in claims:
        return claims
    url, access = meta.get("userinfo_endpoint"), tokens.get("access_token")
    if not url or not access:
        return claims
    try:
        async with _http() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access}"})
        info = resp.json() if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        info = {}
    if info.get("sub") != claims["sub"]:
        return claims
    merged = dict(info)
    merged.update(claims)
    return merged


def _enabled_row(row: sqlite3.Row) -> sqlite3.Row:
    if row["disabled"]:
        log.info("Refused SSO sign-in for disabled user '%s'", row["username"])
        raise OIDCError(DISABLED_MESSAGE, 403)
    return row


def _unique_username(c: sqlite3.Connection, claims: dict) -> str:
    raw = claims.get("preferred_username") or (claims.get("email") or "").split("@")[0] or "user"
    base = re.sub(r"[^a-z0-9._@-]", "", normalize_username(str(raw)).replace(" ", "."))
    base = base.lstrip("._@-")[:56] or "user"
    name, n = base, 1
    reserved = normalize_username(os.environ.get("ADMIN_USER", ""))  # never hand out the bootstrap admin's name
    while find_user(c, name) or name == reserved:
        n += 1
        name = f"{base}{n}"
    return name


def _claims_issuer(c: sqlite3.Connection, claims: dict) -> str:
    return normalize_issuer(str(claims.get("iss") or current_issuer(c)))


def find_identity(c: sqlite3.Connection, iss: str, sub: str) -> sqlite3.Row | None:
    """The user linked to (iss, sub). A row with no issuer yet matches the issuer in effect."""
    return c.execute("SELECT * FROM users WHERE oidc_sub=? AND (oidc_iss=? OR oidc_iss IS NULL) "
                     "ORDER BY oidc_iss IS NULL LIMIT 1", (sub, iss)).fetchone()


def _insert_sso_user(c: sqlite3.Connection, claims: dict, iss: str, admin: bool) -> sqlite3.Row:
    name = _unique_username(c, claims)
    display = str(claims.get("name") or "").strip()[:100] or name
    email = (claims.get("email") or "").strip()
    try:
        cur = c.execute("INSERT INTO users(username, display_name, oidc_sub, oidc_iss, email, is_admin) "
                        "VALUES (?,?,?,?,?,?)", (name, display, str(claims["sub"]), iss, email or None, int(admin)))
    except sqlite3.IntegrityError:
        raise OIDCError("This single sign-on login is already linked to another Macrolog user.", 409) from None
    log.info("Created %s '%s' from SSO login", "administrator" if admin else "user", name)
    return c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()


def _link_by_email(c: sqlite3.Connection, claims: dict, iss: str) -> sqlite3.Row | None:
    email = (claims.get("email") or "").strip()
    if not email or claims.get("email_verified") is not True:
        return None
    rows = c.execute("SELECT * FROM users WHERE lower(email)=lower(?) AND oidc_sub IS NULL", (email,)).fetchall()
    if len(rows) != 1:
        return None
    row = _enabled_row(rows[0])
    c.execute("UPDATE users SET oidc_sub=?, oidc_iss=? WHERE id=?", (str(claims["sub"]), iss, row["id"]))
    config.audit(c, row["id"], "sso.linked_by_email", f"{row['username']} (id {row['id']})", f"issuer {iss}")
    log.info("Linked SSO login to existing user '%s' by verified email", row["username"])
    return row


def _first_user_from_sso(c: sqlite3.Connection, claims: dict, iss: str) -> sqlite3.Row:
    """No users yet. With password sign-in on, the setup screen comes first; with it off, SSO makes the admin."""
    if config.flag("local_login", c):
        raise OIDCError(SETUP_FIRST, 403)
    row = _insert_sso_user(c, claims, iss, admin=True)
    config.audit(c, row["id"], "setup.first_admin_sso", f"{row['username']} (id {row['id']})", f"issuer {iss}")
    return row


def _resolve_user(c: sqlite3.Connection, claims: dict) -> sqlite3.Row:
    sub, iss = str(claims["sub"]), _claims_issuer(c, claims)
    row = find_identity(c, iss, sub)
    if row:
        row = _enabled_row(row)
        if row["oidc_iss"] is None:
            c.execute("UPDATE users SET oidc_iss=? WHERE id=?", (iss, row["id"]))
        return row
    row = _link_by_email(c, claims, iss)
    if row:
        return row
    if user_count(c) == 0:
        return _first_user_from_sso(c, claims, iss)
    if not config.flag("oidc_allow_signup"):
        raise OIDCError("No Macrolog account is linked to this login. Ask the administrator to create one.", 403)
    return _insert_sso_user(c, claims, iss, admin=False)


def _error_page(message: str, status: int, back: str = "/") -> HTMLResponse:
    body = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>Sign-in failed</title><p>{html.escape(message)}</p>"
        f"<p><a href='{html.escape(back, quote=True)}'>Back to Macrolog</a></p>"
    )
    return HTMLResponse(body, status_code=status)


def _require_oidc() -> None:
    if not oidc_enabled():
        raise HTTPException(404, "Single sign-on is not configured on this server")


# ---------------------------------------------------------------- OIDC routes

SETTINGS_PATH = "/#settings"  # where link mode returns; the frontend opens Settings for this hash


async def _begin(request: Request, flow_extra: dict, back: str = "/"):
    """Store a fresh flow (state, nonce, PKCE) in the session and redirect to the provider."""
    try:
        meta = await discovery()
    except OIDCError as exc:
        return _error_page(str(exc), exc.status, back)
    verifier, challenge = _pkce_pair()
    flow = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32), "verifier": verifier,
            "ts": time.time(), **flow_extra}
    request.session["oidc"] = flow
    params = {
        "response_type": "code", "client_id": oidc_client_id(), "redirect_uri": redirect_uri(),
        "scope": "openid email profile", "state": flow["state"], "nonce": flow["nonce"],
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return RedirectResponse(meta["authorization_endpoint"] + sep + urlencode(params), status_code=302)


@router.get("/auth/oidc/login")
async def oidc_login(request: Request, next: str | None = None):
    _require_oidc()
    return await _begin(request, {"next": safe_next(next)})


def _session_user(request: Request) -> dict | None:
    try:
        return deps.current_user(request)
    except HTTPException:
        return None


@router.get("/auth/oidc/link")
async def oidc_link(request: Request):
    """Start SSO in link mode for the signed-in user (Settings > Connect SSO)."""
    _require_oidc()
    if request.headers.get("sec-fetch-site", "").lower() not in ("", "same-origin", "none"):
        return _error_page("Start linking from the Settings page in Macrolog.", 403, SETTINGS_PATH)
    user = _session_user(request)
    if user is None:
        return _error_page("Sign in first, then use Connect SSO in Settings.", 401)
    with db.conn() as c:
        linked = c.execute("SELECT oidc_sub FROM users WHERE id=?", (user["id"],)).fetchone()["oidc_sub"]
    if linked:
        return _error_page("Your account is already linked to single sign-on. Unlink it first to "
                           "connect a different login.", 409, SETTINGS_PATH)
    extra = {"mode": "link", "uid": user["id"], "sv": request.session.get("sv", 0)}
    return await _begin(request, extra, SETTINGS_PATH)


@router.get("/auth/oidc/callback")
async def oidc_callback(request: Request, state: str | None = None, code: str | None = None,
                        error: str | None = None):
    _require_oidc()
    flow = request.session.pop("oidc", None)  # consumed exactly once, whatever happens next
    if isinstance(flow, dict) and flow.get("mode") == "link":
        try:
            await _finish_link(request, flow, state, code, error)
        except OIDCError as exc:
            return _error_page(str(exc), exc.status, SETTINGS_PATH)
        return RedirectResponse(SETTINGS_PATH, status_code=302)
    try:
        user_id, target = await _finish_oidc(flow, state, code, error)
    except OIDCError as exc:
        return _error_page(str(exc), exc.status)
    _start_session(request, user_id)
    return RedirectResponse(target, status_code=302)


async def _verified_claims(flow: dict | None, state: str | None, code: str | None, error: str | None) -> dict:
    """Check state, exchange the code, verify the id_token (signature, iss, aud, exp, nonce)."""
    if not isinstance(flow, dict) or time.time() - float(flow.get("ts", 0)) > OIDC_FLOW_TTL:
        raise OIDCError("Your sign-in attempt expired. Please start again.")
    if not state or not hmac.compare_digest(str(flow.get("state", "")), state):
        raise OIDCError("Sign-in failed: invalid state. Please start again.")
    if error or not code:
        log.info("OIDC provider returned error=%s", (error or "missing code")[:64])
        raise OIDCError("Sign-in was cancelled or refused by the provider.")
    meta = await discovery()
    tokens = await _exchange_code(meta, code, flow["verifier"])
    claims = await _decode_id_token(meta, tokens["id_token"])
    _validate_claims(claims, meta["issuer"], flow["nonce"])
    return await _userinfo(meta, tokens, claims)


async def _finish_oidc(flow: dict | None, state: str | None, code: str | None, error: str | None) -> tuple[int, str]:
    claims = await _verified_claims(flow, state, code, error)
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")  # serializes the first-user check and the link/stamp writes
        row = _resolve_user(c, claims)
    return row["id"], safe_next(flow.get("next"))


def _check_link_session(request: Request, flow: dict) -> int:
    """The link flow must finish in the same, still valid session of the user who started it."""
    user = _session_user(request)
    if user is None or user["id"] != flow.get("uid") or request.session.get("sv", 0) != flow.get("sv"):
        raise OIDCError("Your Macrolog session changed while linking. Sign in and start again from Settings.", 403)
    return user["id"]


def _link_sub(c: sqlite3.Connection, uid: int, iss: str, sub: str) -> None:
    c.execute("BEGIN IMMEDIATE")
    row = c.execute("SELECT username, oidc_sub, disabled FROM users WHERE id=?", (uid,)).fetchone()
    if row is None or row["disabled"]:
        raise OIDCError(DISABLED_MESSAGE, 403)
    if row["oidc_sub"]:
        raise OIDCError("Your account is already linked to single sign-on.", 409)
    if find_identity(c, iss, sub):
        raise OIDCError("This single sign-on login is already linked to another Macrolog user.", 409)
    try:
        c.execute("UPDATE users SET oidc_sub=?, oidc_iss=? WHERE id=?", (sub, iss, uid))
    except sqlite3.IntegrityError:
        raise OIDCError("This single sign-on login is already linked to another Macrolog user.", 409) from None
    config.audit(c, uid, "self.sso_link", f"{row['username']} (id {uid})")


async def _finish_link(request: Request, flow: dict, state: str | None, code: str | None,
                       error: str | None) -> None:
    uid = _check_link_session(request, flow)
    claims = await _verified_claims(flow, state, code, error)
    _check_link_session(request, flow)  # still the same session after the network round trips
    with db.conn() as c:
        _link_sub(c, uid, _claims_issuer(c, claims), str(claims["sub"]))
    log.info("User %s linked single sign-on from Settings", uid)


def clear_cache() -> None:
    """Forget cached discovery documents and keys (after the SSO settings change)."""
    _cache.clear()
