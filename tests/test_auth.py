import base64
import hashlib
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from starlette.middleware.sessions import SessionMiddleware

from app import auth, auth_cli, db

ISSUER = "https://auth.example.com/application/o/macrolog/"
BASE = "https://auth.example.com/application/o"
KEY = RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"}, private=True)
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"}, private=True)


class Provider:
    """A fake authentik: discovery, JWKS, token and userinfo endpoints."""

    def __init__(self):
        self.challenge = None
        self.nonce = None
        self.claims = {}
        self.key = KEY
        self.token_requests = []
        self.userinfo = None

    def id_token(self):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": "client-1", "sub": "sub-1", "iat": now, "exp": now + 300,
                  "nonce": self.nonce, "email": "ann@example.com", "email_verified": True,
                  "preferred_username": "Ann", "name": "Ann Example"}
        claims.update(self.claims)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, self.key)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == ISSUER + ".well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": BASE + "/authorize/",
                "token_endpoint": BASE + "/token/", "jwks_uri": ISSUER + "jwks/",
                "userinfo_endpoint": BASE + "/userinfo/"})
        if url == ISSUER + "jwks/":
            return httpx.Response(200, json={"keys": [KEY.as_dict(private=False)]})
        if url == BASE + "/token/":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            verifier = form["code_verifier"][0]
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if digest != self.challenge or form["code"] != ["good-code"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer", "id_token": self.id_token()})
        if url == BASE + "/userinfo/" and self.userinfo is not None:
            return httpx.Response(200, json=self.userinfo)
        return httpx.Response(404)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(auth, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(p.handle)))
    monkeypatch.setattr(auth, "_cache", {})
    return p


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    for name in ("LOCAL_LOGIN", "OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_NAME",
                 "OIDC_ALLOW_SIGNUP", "TRUST_PROXY", "ADMIN_USER", "ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)  # fast hashes in tests; params live in the hash string
    with db.conn() as c:
        db.init_shared(c)
        auth.init(c)
        auth.create_user(c, "Alice", "correct horse", "Alice A")


def make_client():
    api = FastAPI()
    api.add_middleware(SessionMiddleware, secret_key="test", session_cookie="macrolog_session", same_site="lax")
    api.include_router(auth.router)
    return TestClient(api, follow_redirects=False)


@pytest.fixture
def client(env):
    return make_client()


@pytest.fixture
def oidc(env, provider, monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-1")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "1")  # most SSO tests exercise account creation
    return provider


def login(client, username="alice", password="correct horse", **kw):
    return client.post("/api/auth/login", json={"username": username, "password": password}, **kw)


def start_sso(client, provider, next_path=None):
    resp = client.get("/auth/oidc/login", params={"next": next_path} if next_path else None)
    assert resp.status_code == 302
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    provider.challenge = query["code_challenge"][0]
    provider.nonce = query["nonce"][0]
    return query


def sso(client, provider, next_path=None, **claims):
    query = start_sso(client, provider, next_path)
    provider.claims.update(claims)
    return client.get("/auth/oidc/callback", params={"state": query["state"][0], "code": "good-code"})


def users():
    with db.conn() as c:
        return {r["username"]: dict(r) for r in c.execute("SELECT * FROM users")}


# ---------------------------------------------------------------- passwords

def test_hash_format_and_verify(env, monkeypatch):
    monkeypatch.setattr(auth, "SCRYPT_N", 2**15)
    h = auth.hash_password("pw-123456")
    assert h.startswith("scrypt$32768$8$1$")
    assert auth.verify_password("pw-123456", h)
    assert not auth.verify_password("pw-1234567", h)
    assert auth.hash_password("pw-123456") != h  # per-user random salt
    assert not auth.verify_password("x", None)
    assert not auth.verify_password("x", "garbage")


def test_old_params_still_verify_and_rehash(env, monkeypatch):
    old = auth.hash_password("correct horse")
    with db.conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE username='alice'", (old,))
    monkeypatch.setattr(auth, "SCRYPT_N", 2**11)
    assert login(make_client()).status_code == 200
    assert users()["alice"]["password_hash"].startswith("scrypt$2048$")


# ---------------------------------------------------------------- local login

def test_config_defaults(client):
    assert client.get("/api/auth/config").json() == {"local": True, "oidc": False, "oidc_name": "authentik",
                                                     "needs_setup": False, "first_admin_via_sso": False}


def test_config_with_oidc(oidc, client, monkeypatch):
    monkeypatch.setenv("OIDC_NAME", "Home SSO")
    monkeypatch.setenv("LOCAL_LOGIN", "0")
    assert client.get("/api/auth/config").json() == {"local": False, "oidc": True, "oidc_name": "Home SSO",
                                                     "needs_setup": False, "first_admin_via_sso": False}


def test_login_me_logout(client):
    assert client.get("/api/auth/me").status_code == 401
    resp = login(client, username="  ALICE ")  # case-insensitive
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice" and resp.json()["display_name"] == "Alice A"
    assert client.get("/api/auth/me").json()["username"] == "alice"
    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_user_same_error(client):
    a = login(client, password="nope nope")
    b = login(client, username="nobody")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Wrong username or password"}
    assert client.get("/api/auth/me").status_code == 401


def test_unknown_user_still_hashes(client, monkeypatch):
    calls = []
    real = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda p, s: calls.append(s) or real(p, s))
    login(client, username="nobody")
    assert calls and calls[0].startswith("scrypt$")


def test_sso_only_user_cannot_password_login(client):
    with db.conn() as c:
        c.execute("INSERT INTO users(username, oidc_sub) VALUES ('bob', 'x')")
    assert login(client, username="bob", password="").status_code == 401


def test_session_fixation_cleared_on_login(env):
    api = FastAPI()
    api.add_middleware(SessionMiddleware, secret_key="test")
    api.include_router(auth.router)

    @api.get("/plant")
    def plant(request: auth.Request):
        request.session["planted"] = "x"
        return {}

    @api.get("/peek")
    def peek(request: auth.Request):
        return dict(request.session)

    c = TestClient(api)
    c.get("/plant")
    login(c)
    assert "planted" not in c.get("/peek").json()


def test_rate_limit_per_username(client):
    for _ in range(auth.RATE_MAX_USER):
        assert login(client, password="bad password").status_code == 401
    resp = login(client)  # right password, still locked
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0
    assert "Too many" in resp.json()["detail"]
    assert login(make_client()).status_code == 429  # persisted in the DB, survives a new app
    assert login(client, username="ALICE").status_code == 429  # case-insensitive key


def test_rate_limit_unknown_user_looks_the_same(client):
    for _ in range(auth.RATE_MAX_USER):
        login(client, username="ghost")
    assert login(client, username="ghost").status_code == 429


def test_rate_limit_window_expires(client, monkeypatch):
    for _ in range(auth.RATE_MAX_USER):
        login(client, password="bad password")
    now = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: now + auth.RATE_WINDOW + 1)
    assert login(client).status_code == 200


def test_success_resets_user_counter(client):
    for _ in range(auth.RATE_MAX_USER - 1):
        login(client, password="bad password")
    assert login(client).status_code == 200
    assert login(client, password="bad password").status_code == 401


def test_rate_limit_per_ip_and_trust_proxy(client, monkeypatch):
    monkeypatch.setattr(auth, "RATE_MAX_IP", 3)
    for i in range(3):
        login(client, username=f"u{i}")
    assert login(client).status_code == 429
    # A spoofed X-Forwarded-For is ignored without TRUST_PROXY
    assert login(client, headers={"X-Forwarded-For": "9.9.9.9"}).status_code == 429
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert login(client, headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}).status_code == 200


def test_local_login_disabled(client, monkeypatch):
    monkeypatch.setenv("LOCAL_LOGIN", "0")
    resp = login(client)
    assert resp.status_code == 404 and "disabled" in resp.json()["detail"]


def test_cross_origin_post_rejected(client):
    assert login(client, headers={"Origin": "https://evil.example"}).status_code == 403
    assert login(client, headers={"Origin": "null"}).status_code == 403
    assert login(client, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def _burst(n, make_call):
    """Run n calls at the same moment on separate clients. Returns their status codes."""
    gate, codes = threading.Barrier(n), []

    def run(i):
        client = make_client()
        gate.wait()
        codes.append(make_call(client, i))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return codes


def test_parallel_wrong_guesses_only_five_evaluated(client, monkeypatch):
    seen = []
    real = auth.verify_password

    def slow(password, stored):
        seen.append(password)
        time.sleep(0.05)  # widen the old check-then-record race
        return real(password, stored)

    monkeypatch.setattr(auth, "verify_password", slow)
    codes = _burst(16, lambda c, i: login(c, password=f"wrong guess {i}").status_code)
    assert sorted(codes) == [401] * auth.RATE_MAX_USER + [429] * (16 - auth.RATE_MAX_USER)
    assert len(seen) == auth.RATE_MAX_USER
    assert login(client).status_code == 429  # even the right password is blocked now


def test_parallel_right_password_is_not_counted_against_the_user(client):
    codes = _burst(6, lambda c, i: login(c).status_code)
    assert codes == [200] * 6
    with db.conn() as c:
        assert c.execute("SELECT count(*) FROM login_failures").fetchone()[0] == 0


def test_success_resets_counters_and_clears_pending(client):
    for _ in range(auth.RATE_MAX_USER - 1):
        assert login(client, password="bad password").status_code == 401
    assert login(client).status_code == 200
    with db.conn() as c:
        keys = [r["key"] for r in c.execute("SELECT key FROM login_failures")]
    assert keys == ["ip:testclient"] * (auth.RATE_MAX_USER - 1)  # user key reset, no pending row left


def test_scrypt_concurrency_is_bounded(client, monkeypatch):
    monkeypatch.setattr(auth, "SCRYPT_SLOTS", threading.Semaphore(2))
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(password, stored):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return False

    monkeypatch.setattr(auth, "verify_password", slow)
    codes = _burst(8, lambda c, i: login(c, username=f"user{i}").status_code)
    assert codes == [401] * 8 and state["max"] == 2


# ---------------------------------------------------------------- session version

def test_session_stores_version_and_set_password_revokes(client, monkeypatch):
    assert login(client).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    answers = iter(["new password 1", "new password 1"])
    monkeypatch.setattr(auth_cli.getpass, "getpass", lambda prompt="": next(answers))
    assert auth_cli.main(["set-password", "alice"]) == 0
    assert users()["alice"]["session_version"] == 1
    assert client.get("/api/auth/me").status_code == 401  # old cookie is dead
    assert login(client, password="new password 1").status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_auth_set_password_bumps_version(env):
    with db.conn() as c:
        auth.set_password(c, "alice", "another password")
        auth.set_password(c, "alice", "third password")
    assert users()["alice"]["session_version"] == 2


def test_rehash_on_login_does_not_revoke_sessions(client, monkeypatch):
    with db.conn() as c:
        c.execute("UPDATE users SET password_hash=?", (auth.hash_password("correct horse"),))
    monkeypatch.setattr(auth, "SCRYPT_N", 2**11)  # stored hash is now outdated
    assert login(client).status_code == 200
    assert users()["alice"]["session_version"] == 0 and client.get("/api/auth/me").status_code == 200


def test_oidc_session_carries_version(oidc, client):
    assert sso(client, oidc).status_code == 302
    assert client.get("/api/auth/me").status_code == 200
    with db.conn() as c:
        c.execute("UPDATE users SET session_version=session_version+1")
    assert client.get("/api/auth/me").status_code == 401


def test_logout_still_clears_cookie(client):
    login(client)
    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401


def test_session_version_migration_on_old_database(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT,"
                " password_hash TEXT, oidc_sub TEXT UNIQUE, email TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    old.execute("INSERT INTO users(username) VALUES ('legacy')")
    old.commit()
    old.close()
    monkeypatch.setenv("DB_PATH", str(path))
    for _ in range(2):  # idempotent
        with db.conn() as c:
            db.init_shared(c)
    with db.conn() as c:
        assert c.execute("SELECT session_version FROM users").fetchone()[0] == 0


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize("value,expected", [
    (None, "/"), ("/", "/"), ("/day?d=1", "/day?d=1"), ("//evil.com", "/"), ("/\\evil.com", "/"),
    ("https://evil.com/", "/"), ("evil.com", "/"), ("/\t/evil.com", "/"), ("javascript:alert(1)", "/"),
])
def test_safe_next(value, expected):
    assert auth.safe_next(value) == expected


# ---------------------------------------------------------------- OIDC

def test_oidc_routes_404_when_unconfigured(client):
    resp = client.get("/auth/oidc/login")
    assert resp.status_code == 404 and "not configured" in resp.json()["detail"]
    assert client.get("/auth/oidc/callback?state=x&code=y").status_code == 404


def test_oidc_login_redirect(oidc, client):
    resp = client.get("/auth/oidc/login")
    loc = urlsplit(resp.headers["location"])
    q = parse_qs(loc.query)
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == BASE + "/authorize/"
    assert q["response_type"] == ["code"] and q["client_id"] == ["client-1"]
    assert q["redirect_uri"] == ["http://testserver/auth/oidc/callback"]
    assert q["scope"] == ["openid email profile"]
    assert q["code_challenge_method"] == ["S256"]
    assert len(q["state"][0]) > 30 and len(q["nonce"][0]) > 30


def test_oidc_happy_path_new_user(oidc, client):
    resp = sso(client, oidc, next_path="/today")
    assert resp.status_code == 302 and resp.headers["location"] == "/today"
    me = client.get("/api/auth/me").json()
    assert me["username"] == "ann" and me["display_name"] == "Ann Example"
    u = users()["ann"]
    assert u["oidc_sub"] == "sub-1" and u["email"] == "ann@example.com" and u["password_hash"] is None
    form = oidc.token_requests[0]
    assert form["redirect_uri"] == ["http://testserver/auth/oidc/callback"]
    assert form["client_secret"] == ["s3cret"]


def test_oidc_returning_user_by_sub(oidc, client):
    sso(client, oidc)
    client.post("/api/auth/logout")
    oidc.claims = {"preferred_username": "renamed", "email": "new@example.com"}
    assert sso(client, oidc).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "ann"
    assert len(users()) == 2


def test_oidc_links_verified_email(oidc, client):
    with db.conn() as c:
        auth.set_email(c, "alice", "Ann@Example.com")
    assert sso(client, oidc).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "alice"
    assert users()["alice"]["oidc_sub"] == "sub-1"
    assert len(users()) == 1


def test_oidc_unverified_email_does_not_link(oidc, client):
    with db.conn() as c:
        auth.set_email(c, "alice", "ann@example.com")
    assert sso(client, oidc, email_verified=False).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "ann"
    assert users()["alice"]["oidc_sub"] is None


def test_oidc_username_collision_deduplicated(oidc, client):
    assert sso(client, oidc, preferred_username="Alice", email=None).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "alice2"


def test_oidc_bad_state(oidc, client):
    query = start_sso(client, oidc)
    resp = client.get("/auth/oidc/callback", params={"state": "forged", "code": "good-code"})
    assert resp.status_code == 400 and "invalid state" in resp.text
    # The flow was consumed: replaying the right state now fails too
    resp = client.get("/auth/oidc/callback", params={"state": query["state"][0], "code": "good-code"})
    assert resp.status_code == 400 and "expired" in resp.text
    assert client.get("/api/auth/me").status_code == 401


def test_oidc_callback_without_flow(oidc, client):
    assert client.get("/auth/oidc/callback", params={"state": "a", "code": "b"}).status_code == 400


def test_oidc_state_single_use(oidc, client):
    query = start_sso(client, oidc)
    params = {"state": query["state"][0], "code": "good-code"}
    assert client.get("/auth/oidc/callback", params=params).status_code == 302
    client.post("/api/auth/logout")
    assert client.get("/auth/oidc/callback", params=params).status_code == 400


@pytest.mark.parametrize("claims,reason", [
    ({"nonce": "wrong"}, "nonce"),
    ({"aud": "other-client"}, "audience"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"iss": "https://evil.example/"}, "issuer"),
    ({"sub": None}, "missing sub"),
])
def test_oidc_bad_claims_rejected(oidc, client, claims, reason):
    query = start_sso(client, oidc)
    oidc.claims.update(claims)
    if "nonce" in claims:
        oidc.nonce = claims["nonce"]
    resp = client.get("/auth/oidc/callback", params={"state": query["state"][0], "code": "good-code"})
    assert resp.status_code == 400, reason
    assert client.get("/api/auth/me").status_code == 401
    assert "ann" not in users()


def test_oidc_bad_signature(oidc, client):
    oidc.key = OTHER_KEY
    resp = sso(client, oidc)
    assert resp.status_code == 400 and "could not be verified" in resp.text
    assert client.get("/api/auth/me").status_code == 401


def test_oidc_provider_error_param(oidc, client):
    query = start_sso(client, oidc)
    resp = client.get("/auth/oidc/callback", params={"state": query["state"][0], "error": "access_denied"})
    assert resp.status_code == 400 and "cancelled" in resp.text


def test_oidc_signup_disabled_by_default(oidc, client, monkeypatch):
    monkeypatch.delenv("OIDC_ALLOW_SIGNUP")
    resp = sso(client, oidc)
    assert resp.status_code == 403 and "No Macrolog account" in resp.text
    assert "ann" not in users()


def test_oidc_signup_disabled_still_links_verified_email(oidc, client, monkeypatch):
    monkeypatch.delenv("OIDC_ALLOW_SIGNUP")  # the default
    with db.conn() as c:
        auth.set_email(c, "alice", "ann@example.com")
    assert sso(client, oidc).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "alice"


@pytest.mark.parametrize("target", ["https://evil.com/x", "//evil.com", "/\\evil.com"])
def test_oidc_open_redirect_guard(oidc, client, target):
    resp = sso(client, oidc, next_path=target)
    assert resp.status_code == 302 and resp.headers["location"] == "/"


def test_oidc_userinfo_fallback(oidc, client):
    oidc.userinfo = {"sub": "sub-1", "preferred_username": "fromuserinfo", "email": "u@example.com"}
    assert sso(client, oidc, preferred_username=None, email=None, email_verified=None).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "fromuserinfo"


def test_oidc_discovery_issuer_mismatch(oidc, client, monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://auth.example.com/application/o/other/")
    resp = client.get("/auth/oidc/login")
    assert resp.status_code == 502


def test_oidc_issuer_without_trailing_slash(oidc, client, monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER.rstrip("/"))
    assert sso(client, oidc).status_code == 302


def test_oidc_login_clears_old_session(oidc, client):
    login(client)
    assert sso(client, oidc).status_code == 302
    assert client.get("/api/auth/me").json()["username"] == "ann"


def test_oidc_disabled_user_refused(oidc, client):
    assert sso(client, oidc).status_code == 302
    client.post("/api/auth/logout")
    with db.conn() as c:
        c.execute("UPDATE users SET disabled=1 WHERE username='ann'")
    resp = sso(client, oidc)
    assert resp.status_code == 403 and "disabled" in resp.text
    assert client.get("/api/auth/me").status_code == 401


def test_oidc_does_not_link_disabled_user_by_email(oidc, client):
    with db.conn() as c:
        auth.set_email(c, "alice", "ann@example.com")
        c.execute("UPDATE users SET disabled=1 WHERE username='alice'")
    assert sso(client, oidc).status_code == 403
    assert users()["alice"]["oidc_sub"] is None and "ann" not in users()


def test_oidc_settings_from_config_store(oidc, client, monkeypatch):
    from app import config
    monkeypatch.delenv("OIDC_CLIENT_ID")
    monkeypatch.delenv("OIDC_CLIENT_SECRET")
    assert client.get("/api/auth/config").json()["oidc"] is False
    with db.conn() as c:
        config.store(c, "oidc_client_id", "client-1")
        config.store(c, "oidc_client_secret", "stored-secret")
        config.store(c, "oidc_name", "Stored SSO")
    assert client.get("/api/auth/config").json() == {"local": True, "oidc": True, "oidc_name": "Stored SSO",
                                                     "needs_setup": False, "first_admin_via_sso": False}
    assert sso(client, oidc).status_code == 302
    assert oidc.token_requests[0]["client_secret"] == ["stored-secret"]


def test_disabled_password_user_refused(client):
    with db.conn() as c:
        c.execute("UPDATE users SET disabled=1 WHERE username='alice'")
    assert login(client).status_code == 403
    assert login(client, password="wrong password").status_code == 401  # no hint without the password
    assert client.get("/api/auth/me").status_code == 401


def test_secrets_not_logged(oidc, client, caplog):
    caplog.set_level("DEBUG")
    sso(client, oidc, aud="other-client")
    login(client, password="hunter2-secret")
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("macrolog"))
    assert ours
    for secret in ("s3cret", "hunter2-secret", "good-code", "correct horse"):
        assert secret not in ours


# ---------------------------------------------------------------- bootstrap and CLI

def test_bootstrap_admin_only_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)
    monkeypatch.setenv("ADMIN_USER", "Admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-1")
    auth.bootstrap_admin()
    assert set(users()) == {"admin"}
    first = users()["admin"]["password_hash"]
    monkeypatch.setenv("ADMIN_USER", "other")
    auth.bootstrap_admin()
    assert set(users()) == {"admin"} and users()["admin"]["password_hash"] == first


def test_bootstrap_admin_noop_without_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    auth.bootstrap_admin()
    with db.conn() as c:
        db.init_shared(c)
        assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_cli(env, monkeypatch, capsys):
    answers = iter(["pw-long-enough", "pw-long-enough"])
    monkeypatch.setattr(auth_cli.getpass, "getpass", lambda prompt="": next(answers))
    assert auth_cli.main(["add-user", "Bob", "--name", "Bob B", "--email", "bob@example.com"]) == 0
    assert login(make_client(), "bob", "pw-long-enough").status_code == 200
    assert auth_cli.main(["add-user", "BOB"]) == 1
    assert "already exists" in capsys.readouterr().err

    answers = iter(["new-password-1", "new-password-1"])
    assert auth_cli.main(["set-password", "bob"]) == 0
    assert login(make_client(), "bob", "new-password-1").status_code == 200

    answers = iter(["short", "short"])
    assert auth_cli.main(["set-password", "bob"]) == 1
    answers = iter(["mismatch-one", "mismatch-two"])
    assert auth_cli.main(["set-password", "bob"]) == 1
    assert auth_cli.main(["set-password", "nobody"]) == 1
    capsys.readouterr()

    assert auth_cli.main(["list-users"]) == 0
    out = capsys.readouterr().out
    assert "bob\tBob B\tbob@example.com\tpassword" in out and "alice" in out
    assert "scrypt" not in out
