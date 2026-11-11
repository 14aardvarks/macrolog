"""Administration API: users, live configuration, SSO test and an audit log.

Every route requires an administrator (deps.require_admin) and same-origin requests for writes.
Request bodies are parsed by hand rather than with pydantic models so a validation error can
never echo a submitted password or secret back in the response.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from typing import Annotated, Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from . import auth, config, db, deps

log = logging.getLogger("macrolog.admin")

router = APIRouter(prefix="/api/admin", dependencies=[Depends(deps.require_admin), Depends(auth.require_same_origin)])
Admin = Annotated[dict, Depends(deps.require_admin)]

LOG_LIMIT = 50
PROBE_TIMEOUT = 5.0
PROBE_MAX_BYTES = 1024 * 1024
PROBE_MAX_REDIRECTS = 3
MAX_DISPLAY_NAME = 100
MAX_EMAIL = 254
LOCKOUT_KEYS = ("local_login", "oidc_issuer", "oidc_client_id")
ENV_NOTE = "These are set in the environment (.env) and need a restart to change."
_transport = None  # tests set an httpx.MockTransport here

def init(c: sqlite3.Connection) -> None:
    config.init(c)  # creates admin_log too


log_action = config.audit  # (c, admin_id, action, target, detail=""); never pass secret values


# ---------------------------------------------------------------- body helpers

def _object(body: Any, allowed: set[str], required: tuple[str, ...] = ()) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(400, "Send a JSON object")
    unknown = sorted(k for k in body if k not in allowed)
    if unknown:
        raise HTTPException(400, "Unknown field(s): " + ", ".join(str(k)[:40] for k in unknown[:5]))
    missing = [k for k in required if body.get(k) is None]
    if missing:
        raise HTTPException(400, "Missing field(s): " + ", ".join(missing))
    return body


def _bool(body: dict, key: str) -> bool:
    if not isinstance(body[key], bool):
        raise HTTPException(400, f"{key} must be true or false")
    return body[key]


def _text(value: Any, key: str, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(400, f"{key} must be a string")
    value = value.strip()
    if len(value) > max_len or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise HTTPException(400, f"{key} must be at most {max_len} characters without control characters")
    return value


def _email(value: Any) -> Optional[str]:
    email = _text(value, "email", MAX_EMAIL)
    if email and ("@" not in email or any(ch.isspace() for ch in email)):
        raise HTTPException(400, "email is not a valid address")
    return email or None


def _password(value: Any) -> str:
    if not isinstance(value, str):
        raise HTTPException(400, "password must be a string")
    try:
        auth.validate_password(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return value


# ---------------------------------------------------------------- users

def user_dict(c: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "email": row["email"], "is_admin": bool(row["is_admin"]), "disabled": bool(row["disabled"]),
            "use_global_ai": bool(row["use_global_ai"]), "has_password": row["password_hash"] is not None,
            "sso_linked": row["oidc_sub"] is not None, "created_at": row["created_at"],
            "personal_key_set": config.user_secret_state(c, row["id"], auth.PERSONAL_KEY) == "set"}


def _user_row(c: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No such user")
    return row


@router.get("/users")
def list_users(admin: Admin) -> dict:
    with db.conn() as c:
        rows = c.execute("SELECT * FROM users ORDER BY id").fetchall()
        return {"users": [user_dict(c, r) for r in rows]}


@router.post("/users")
def create_user(admin: Admin, body: Any = Body(None)) -> dict:
    body = _object(body, {"username", "display_name", "email", "password", "is_admin"}, ("username", "password"))
    if not isinstance(body["username"], str):
        raise HTTPException(400, "username must be a string")
    password = _password(body["password"])
    display = _text(body.get("display_name"), "display_name", MAX_DISPLAY_NAME)
    email = _email(body.get("email"))
    make_admin = _bool(body, "is_admin") if body.get("is_admin") is not None else False
    try:
        name = auth.validate_username(body["username"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if auth.find_user(c, name):
            raise HTTPException(409, f"User '{name}' already exists")
        uid = auth.create_user(c, name, password, display, email)
        if make_admin:
            c.execute("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
        log_action(c, admin["id"], "user.create", f"{name} (id {uid})", "administrator" if make_admin else "")
        return user_dict(c, _user_row(c, uid))


def _patch_values(c: sqlite3.Connection, row: sqlite3.Row, body: dict) -> dict:
    changes: dict[str, Any] = {}
    if "display_name" in body:
        changes["display_name"] = _text(body["display_name"], "display_name", MAX_DISPLAY_NAME) or row["username"]
    if "email" in body:
        changes["email"] = _email(body["email"])
    for key in ("is_admin", "disabled", "use_global_ai"):
        if key in body:
            changes[key] = 1 if _bool(body, key) else 0
    if "password" in body:
        changes["password_hash"] = auth.hash_password(_password(body["password"]))
    if "unlink_sso" in body and _bool(body, "unlink_sso") and row["oidc_sub"]:
        changes["oidc_sub"] = None
        changes["oidc_iss"] = None
    return changes


def _guard_user_change(c: sqlite3.Connection, admin: dict, row: sqlite3.Row, changes: dict) -> None:
    new_admin = changes.get("is_admin", row["is_admin"])
    new_disabled = changes.get("disabled", row["disabled"])
    if new_disabled and not row["disabled"] and row["id"] == admin["id"]:
        raise HTTPException(400, "You cannot disable your own account")
    if "oidc_sub" in changes and row["id"] == admin["id"] and \
            (not row["password_hash"] or not config.flag("local_login", c)):
        raise HTTPException(400, "Unlinking your own single sign-on now would lock you out "
                                 "(no password, or password sign-in is off).")
    was_active = row["is_admin"] and not row["disabled"]
    if not was_active:
        return
    stays_active = new_admin and not new_disabled
    if not stays_active and auth.active_admin_count(c, exclude=row["id"]) == 0:
        raise HTTPException(409, "This is the last active administrator. Make someone else an administrator first.")
    loses_sso = not stays_active or ("oidc_sub" in changes and changes["oidc_sub"] is None)
    if loses_sso and row["oidc_sub"] and not config.flag("local_login", c) and \
            auth.active_admin_count(c, exclude=row["id"], sso_only=True) == 0:
        raise HTTPException(409, "Password sign-in is off and this is the last administrator who can sign in "
                                 "with single sign-on.")


def _change_summary(changes: dict) -> str:
    parts = []
    for key, value in changes.items():
        if key == "password_hash":
            parts.append("password reset")
        elif key == "oidc_sub":
            parts.append("SSO unlinked")
        elif key == "oidc_iss":
            continue
        elif key in ("is_admin", "disabled", "use_global_ai"):
            parts.append(f"{key}={'true' if value else 'false'}")
        else:
            parts.append(f"{key} changed")
    return ", ".join(parts)


@router.patch("/users/{user_id}")
def update_user(user_id: int, admin: Admin, body: Any = Body(None)) -> dict:
    body = _object(body, {"display_name", "email", "is_admin", "disabled", "use_global_ai", "password", "unlink_sso"})
    with db.conn() as c:
        changes = _patch_values(c, _user_row(c, user_id), body)  # hashes before taking the write lock
        c.execute("BEGIN IMMEDIATE")
        row = _user_row(c, user_id)
        _guard_user_change(c, admin, row, changes)
        if changes:
            revoke = ("password_hash" in changes or "oidc_sub" in changes
                      or (changes.get("disabled") and not row["disabled"])
                      or (row["is_admin"] and changes.get("is_admin") == 0))
            sets = ", ".join(f"{k}=?" for k in changes) + (", session_version=session_version+1" if revoke else "")
            c.execute(f"UPDATE users SET {sets} WHERE id=?", (*changes.values(), user_id))
            log_action(c, admin["id"], "user.update", f"{row['username']} (id {user_id})", _change_summary(changes))
        return user_dict(c, _user_row(c, user_id))


# ---------------------------------------------------------------- configuration

def _test_record(c: sqlite3.Connection) -> Optional[dict]:
    raw = config.get_internal(c, config.TEST_RECORD_KEY)
    try:
        rec = json.loads(raw) if raw else None
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def _environment() -> dict:
    return {"SECRET_KEY": {"set": bool(os.environ.get("SECRET_KEY"))}, "DB_PATH": db.db_path(),
            "PUBLIC_URL": auth.public_url(), "TRUST_PROXY": auth._flag("TRUST_PROXY", "0"),
            "COOKIE_SECURE": os.environ.get("COOKIE_SECURE", "0") == "1", "note": ENV_NOTE}


def _warnings(settings: dict) -> list[str]:
    out = [f"The stored {key} could not be decrypted (was SECRET_KEY changed?). It is treated as unset; "
           "enter it again." for key, item in settings.items() if item.get("unreadable")]
    if settings["oidc_issuer"]["value"] and not auth.public_url():
        out.append("Single sign-on needs PUBLIC_URL to be set in the environment.")
    return out


AUTHENTIK_CHECKLIST = (
    "Create an OAuth2/OpenID Provider and an Application for Macrolog in authentik.",
    "Client type: Confidential.",
    "Redirect URIs: Strict, set to exactly the redirect URI shown here.",
    "Signing Key: choose an RS256 certificate (for example the authentik self-signed certificate).",
    "Scopes: openid, email and profile.",
    "Turn on 'Include claims in id_token'.",
    "Issuer: copy the provider's OpenID Configuration Issuer, including the trailing slash.",
)
REDIRECT_WARNING = ("PUBLIC_URL is not set in the environment, so the redirect URI is unknown and single "
                    "sign-on cannot work until it is set and Macrolog is restarted.")


def config_view(c: sqlite3.Connection) -> dict:
    settings = config.describe(c)
    rec = _test_record(c)
    if rec:
        rec = {**rec, "matches_current": rec.get("issuer") == auth.normalize_issuer(config.get("oidc_issuer", c=c))
               and rec.get("client_id") == str(config.get("oidc_client_id", c=c)).strip()}
    redirect = auth.redirect_uri() if auth.public_url() else None
    return {"settings": settings, "environment": _environment(), "oidc_test": rec, "warnings": _warnings(settings),
            "oidc_redirect_uri": redirect, "oidc_redirect_uri_warning": None if redirect else REDIRECT_WARNING,
            "authentik_checklist": list(AUTHENTIK_CHECKLIST)}


@router.get("/config")
def get_config(admin: Admin) -> dict:
    with db.conn() as c:
        return config_view(c)


def _after(c: sqlite3.Connection, key: str, changes: dict) -> str:
    """Effective raw value of a setting once `changes` are applied."""
    if key not in changes:
        return str(config.get(key, c=c))
    if changes[key] is not None:
        return changes[key]
    spec = config.MANAGED[key]
    return os.environ.get(spec.env, spec.default)


def _check_issuer_change(c: sqlite3.Connection, changes: dict, local_after: bool) -> None:
    """SSO identities belong to their issuer, so the provider cannot change while password sign-in is off."""
    old = auth.current_issuer(c)
    new = auth.normalize_issuer(_after(c, "oidc_issuer", changes))
    if new != old and (not local_after or not config.flag("local_login", c)):
        raise HTTPException(409, "Turn password sign-in on before changing the SSO provider.")


def _pin_identities(c: sqlite3.Connection, changes: dict) -> None:
    """Before the issuer changes, tie not-yet-stamped SSO links to the issuer they were made with."""
    if "oidc_issuer" in changes:
        auth.pin_unstamped_identities(c, auth.current_issuer(c))


def check_lockout(c: sqlite3.Connection, changes: dict) -> None:
    """Refuse changes that would leave nobody able to sign in."""
    if not any(k in changes for k in LOCKOUT_KEYS):
        return
    local_after = _after(c, "local_login", changes).strip().lower() not in config.FALSE_WORDS
    _check_issuer_change(c, changes, local_after)
    if local_after:
        return
    issuer = auth.normalize_issuer(_after(c, "oidc_issuer", changes))
    client_id = _after(c, "oidc_client_id", changes).strip()
    if not issuer or not client_id:
        raise HTTPException(409, "The SSO issuer and client ID cannot be blank while password sign-in is off.")
    if not auth.public_url():
        raise HTTPException(409, "Password sign-in cannot be off: single sign-on needs PUBLIC_URL in the environment.")
    rec = _test_record(c) or {}
    if rec.get("issuer") != issuer or rec.get("client_id") != client_id:
        raise HTTPException(409, "Run a successful SSO test with these exact issuer and client ID settings "
                                 "before password sign-in can be off.")
    if auth.active_admin_count(c, sso_only=True, issuer=issuer, null_matches=issuer == auth.current_issuer(c)) == 0:
        raise HTTPException(409, "Password sign-in cannot be off until at least one active administrator "
                                 "has signed in with single sign-on.")


def _config_detail(changes: dict) -> str:
    parts = []
    for key, value in changes.items():
        if value is None:
            parts.append(f"{key}: removed override")
        elif config.MANAGED[key].secret:
            parts.append(f"{key}: {'set' if value else 'cleared'}")
        else:
            parts.append(f"{key}={value[:80]}")
    return "; ".join(parts)


@router.put("/config")
def put_config(admin: Admin, body: Any = Body(None)) -> dict:
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "Send a JSON object of setting: value pairs")
    changes: dict[str, Optional[str]] = {}
    try:
        for key, value in body.items():
            changes[str(key)] = config.validate(str(key), value)
    except config.ConfigError as exc:
        raise HTTPException(400, str(exc)) from None
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        check_lockout(c, changes)
        _pin_identities(c, changes)
        try:
            for key, value in changes.items():
                config.store(c, key, value)
        except config.ConfigError as exc:
            raise HTTPException(503, str(exc)) from None
        log_action(c, admin["id"], "config.update", ", ".join(changes), _config_detail(changes))
    if any(k.startswith("oidc_") for k in changes):
        auth.clear_cache()
    with db.conn() as c:
        return config_view(c)


# ---------------------------------------------------------------- OIDC test

class ProbeError(Exception):
    """Test failure with a message safe to show the administrator."""


def _same_host(a: str, b: str) -> bool:
    return (urlsplit(a).hostname or "").lower() == (urlsplit(b).hostname or "").lower()


async def _read_capped(resp: httpx.Response, what: str) -> dict:
    length = resp.headers.get("content-length", "")
    if length.isdigit() and int(length) > PROBE_MAX_BYTES:
        raise ProbeError(f"The {what} response is larger than 1 MB.")
    buf = bytearray()
    async for chunk in resp.aiter_bytes():
        buf += chunk
        if len(buf) > PROBE_MAX_BYTES:
            raise ProbeError(f"The {what} response is larger than 1 MB.")
    try:
        data = json.loads(bytes(buf))
    except ValueError:
        raise ProbeError(f"The {what} response is not JSON.") from None
    if not isinstance(data, dict):
        raise ProbeError(f"The {what} response is not a JSON object.")
    return data


async def _fetch(client: httpx.AsyncClient, url: str, what: str) -> dict:
    """GET JSON, following at most a few redirects and only on the same host."""
    current = url
    for _ in range(PROBE_MAX_REDIRECTS + 1):
        async with client.stream("GET", current) as resp:
            if resp.is_redirect:
                nxt = urljoin(current, resp.headers.get("location", ""))
                if urlsplit(nxt).scheme not in ("http", "https") or not _same_host(nxt, url):
                    raise ProbeError(f"The {what} request was redirected to a different host.")
                current = nxt
                continue
            if resp.status_code != 200:
                raise ProbeError(f"The {what} request returned HTTP {resp.status_code}.")
            return await _read_capped(resp, what)
    raise ProbeError(f"The {what} request was redirected too many times.")


async def _fetch_limited(client: httpx.AsyncClient, url: str, what: str) -> dict:
    try:
        return await asyncio.wait_for(_fetch(client, url, what), PROBE_TIMEOUT)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise ProbeError(f"The {what} request timed out after {PROBE_TIMEOUT:g} seconds.") from None
    except httpx.HTTPError:
        raise ProbeError(f"The {what} request failed: the provider could not be reached.") from None


def _check_meta(meta: dict, issuer: str) -> str:
    reported = meta.get("issuer")
    if reported != issuer:
        shown = str(reported)[:200] if reported is not None else "nothing"
        raise ProbeError(f"Issuer mismatch: the provider reports '{shown}', expected '{issuer}'. "
                         "They must match exactly, including the trailing slash.")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(meta.get(field), str) or not meta[field]:
            raise ProbeError(f"The discovery document is missing {field}.")
    if urlsplit(meta["jwks_uri"]).scheme not in ("http", "https"):
        raise ProbeError("The jwks_uri is not an http or https URL.")
    return meta["jwks_uri"]


def _check_keys(jwks: dict) -> int:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ProbeError("The JWKS response has no signing keys.")
    try:
        KeySet.import_key_set(jwks)
    except (JoseError, ValueError, KeyError, TypeError):
        raise ProbeError("The JWKS signing keys could not be parsed.") from None
    return len(keys)


async def probe(issuer: str) -> str:
    """Check discovery and JWKS for an issuer. Returns a success message or raises ProbeError."""
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT, transport=_transport, follow_redirects=False,
                                 headers={"User-Agent": "macrolog/0.1", "Accept": "application/json"}) as client:
        meta = await _fetch_limited(client, issuer + ".well-known/openid-configuration", "discovery")
        jwks_uri = _check_meta(meta, issuer)
        count = _check_keys(await _fetch_limited(client, jwks_uri, "JWKS"))
    return (f"Discovery and signing keys look good ({count} key(s)). The client ID and secret are checked "
            "by the provider at the first real sign-in.")


def _record_test(c: sqlite3.Connection, issuer: str, client_id: str, ok: bool) -> None:
    rec = _test_record(c) or {}
    if ok:
        config.set_internal(c, config.TEST_RECORD_KEY,
                            json.dumps({"issuer": issuer, "client_id": client_id, "at": config.now_iso()}))
    elif rec.get("issuer") == issuer and rec.get("client_id") == client_id:
        config.set_internal(c, config.TEST_RECORD_KEY, None)  # these settings no longer pass


@router.post("/oidc/test")
async def oidc_test(admin: Admin, body: Any = Body(None)) -> dict:
    """Test the given (or current) issuer and client ID. Body: {"issuer"?, "client_id"?}."""
    body = _object(body if body is not None else {}, {"issuer", "client_id"})
    issuer = body["issuer"] if body.get("issuer") is not None else str(config.get("oidc_issuer"))
    client_id = body["client_id"] if body.get("client_id") is not None else str(config.get("oidc_client_id"))
    try:
        issuer = auth.normalize_issuer(config.validate("oidc_issuer", issuer) or "")
        client_id = config.validate("oidc_client_id", client_id) or ""
    except config.ConfigError as exc:
        raise HTTPException(400, str(exc)) from None
    if not issuer or not client_id:
        return {"ok": False, "message": "Enter an issuer URL and a client ID first."}
    try:
        ok, message = True, await probe(issuer)
    except ProbeError as exc:
        ok, message = False, str(exc)
    if ok:
        auth.clear_cache()  # the next real sign-in rereads discovery and keys
    with db.conn() as c:
        _record_test(c, issuer, client_id, ok)
        log_action(c, admin["id"], "oidc.test", issuer, "passed" if ok else "failed")
    log.info("SSO test for %s %s", issuer, "passed" if ok else "failed")
    return {"ok": ok, "message": message}


# ---------------------------------------------------------------- audit log

@router.get("/log")
def get_log(admin: Admin) -> dict:
    with db.conn() as c:
        rows = c.execute(
            "SELECT l.id, l.at, l.admin_id, u.username AS admin_username, l.action, l.target, l.detail "
            "FROM admin_log l LEFT JOIN users u ON u.id = l.admin_id ORDER BY l.id DESC LIMIT ?", (LOG_LIMIT,)
        ).fetchall()
    return {"entries": [dict(r) for r in rows]}
