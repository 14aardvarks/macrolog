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
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from pydantic import BaseModel, Field

from . import db, deps

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
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,63}$")

_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------- settings

def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def local_enabled() -> bool:
    return _flag("LOCAL_LOGIN", "1")


def oidc_issuer() -> str:
    issuer = os.environ.get("OIDC_ISSUER", "").strip()
    return issuer if not issuer or issuer.endswith("/") else issuer + "/"


def oidc_enabled() -> bool:
    return bool(oidc_issuer() and os.environ.get("OIDC_CLIENT_ID") and public_url())


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
                display_name: str | None = None, email: str | None = None) -> int:
    """Create a local user. Raises ValueError on invalid input or a taken name."""
    name = validate_username(username)
    if password is not None:
        validate_password(password)
    if find_user(c, name):
        raise ValueError(f"User '{name}' already exists")
    cur = c.execute(
        "INSERT INTO users(username, display_name, password_hash, email) VALUES (?,?,?,?)",
        (name, (display_name or "").strip() or name, hash_password(password) if password else None,
         (email or "").strip() or None),
    )
    return cur.lastrowid


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
        " oidc_sub IS NOT NULL AS has_oidc FROM users ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- module API

def init(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS login_failures(
          key TEXT NOT NULL,
          at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS login_failures_key ON login_failures(key, at);
        """
    )


def bootstrap_admin() -> None:
    """Create ADMIN_USER with ADMIN_PASSWORD when the users table is empty."""
    username = os.environ.get("ADMIN_USER", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not username or not password:
        return
    with db.conn() as c:
        db.init_shared(c)
        if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        try:
            create_user(c, username, password)
        except ValueError as exc:
            log.error("ADMIN_USER not created: %s", exc)
            return
    log.info("Created first user '%s' from ADMIN_USER", normalize_username(username))


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
def config() -> dict:
    return {"local": local_enabled(), "oidc": oidc_enabled(),
            "oidc_name": os.environ.get("OIDC_NAME", "").strip() or "authentik"}


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
        if row:
            _forgive(c, keys[0][0], ids)
    if not row:
        log.info("Failed password sign-in from %s", keys[1][0][3:])
        raise HTTPException(401, "Wrong username or password")
    _start_session(request, row["id"])
    return public_user(row)


@router.post("/api/auth/logout", dependencies=[Depends(require_same_origin)])
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/api/auth/me")
def me(user: dict = Depends(deps.current_user)) -> dict:
    return user


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
            "client_id": os.environ["OIDC_CLIENT_ID"], "code_verifier": verifier}
    secret = os.environ.get("OIDC_CLIENT_SECRET")
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
    client_id = os.environ["OIDC_CLIENT_ID"]
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


def _unique_username(c: sqlite3.Connection, claims: dict) -> str:
    raw = claims.get("preferred_username") or (claims.get("email") or "").split("@")[0] or "user"
    base = re.sub(r"[^a-z0-9._@-]", "", normalize_username(str(raw)).replace(" ", "."))
    base = base.lstrip("._@-")[:56] or "user"
    name, n = base, 1
    while find_user(c, name):
        n += 1
        name = f"{base}{n}"
    return name


def _resolve_user(c: sqlite3.Connection, claims: dict) -> sqlite3.Row:
    sub = str(claims["sub"])
    row = c.execute("SELECT * FROM users WHERE oidc_sub=?", (sub,)).fetchone()
    if row:
        return row
    email = (claims.get("email") or "").strip()
    if email and claims.get("email_verified") is True:
        rows = c.execute("SELECT * FROM users WHERE lower(email)=lower(?) AND oidc_sub IS NULL", (email,)).fetchall()
        if len(rows) == 1:
            c.execute("UPDATE users SET oidc_sub=? WHERE id=?", (sub, rows[0]["id"]))
            log.info("Linked SSO login to existing user '%s' by verified email", rows[0]["username"])
            return rows[0]
    if not _flag("OIDC_ALLOW_SIGNUP", "0"):
        raise OIDCError("No Macrolog account is linked to this login. Ask the administrator to create one.", 403)
    name = _unique_username(c, claims)
    display = str(claims.get("name") or "").strip()[:100] or name
    cur = c.execute("INSERT INTO users(username, display_name, oidc_sub, email) VALUES (?,?,?,?)",
                    (name, display, sub, email or None))
    log.info("Created user '%s' from SSO login", name)
    return c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()


def _error_page(message: str, status: int) -> HTMLResponse:
    body = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>Sign-in failed</title><p>{html.escape(message)}</p><p><a href='/'>Back to Macrolog</a></p>"
    )
    return HTMLResponse(body, status_code=status)


def _require_oidc() -> None:
    if not oidc_enabled():
        raise HTTPException(404, "Single sign-on is not configured on this server")


# ---------------------------------------------------------------- OIDC routes

@router.get("/auth/oidc/login")
async def oidc_login(request: Request, next: str | None = None):
    _require_oidc()
    try:
        meta = await discovery()
    except OIDCError as exc:
        return _error_page(str(exc), exc.status)
    verifier, challenge = _pkce_pair()
    flow = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32), "verifier": verifier,
            "next": safe_next(next), "ts": time.time()}
    request.session["oidc"] = flow
    params = {
        "response_type": "code", "client_id": os.environ["OIDC_CLIENT_ID"], "redirect_uri": redirect_uri(),
        "scope": "openid email profile", "state": flow["state"], "nonce": flow["nonce"],
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return RedirectResponse(meta["authorization_endpoint"] + sep + urlencode(params), status_code=302)


@router.get("/auth/oidc/callback")
async def oidc_callback(request: Request, state: str | None = None, code: str | None = None,
                        error: str | None = None):
    _require_oidc()
    flow = request.session.pop("oidc", None)  # consumed exactly once, whatever happens next
    try:
        user_id, target = await _finish_oidc(flow, state, code, error)
    except OIDCError as exc:
        return _error_page(str(exc), exc.status)
    _start_session(request, user_id)
    return RedirectResponse(target, status_code=302)


async def _finish_oidc(flow: dict | None, state: str | None, code: str | None, error: str | None) -> tuple[int, str]:
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
    claims = await _userinfo(meta, tokens, claims)
    with db.conn() as c:
        row = _resolve_user(c, claims)
    return row["id"], safe_next(flow.get("next"))
