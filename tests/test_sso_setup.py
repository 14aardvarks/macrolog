"""Link SSO from Settings, unlink, first-run setup, and the admin setup helper data."""
import base64
import json
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app import admin, ai, auth, config, core, db, main
from conftest import TEST_SECRET_KEY
from test_auth import ISSUER, Provider

PASSWORDS = {"root": "root-password-1", "alice": "alice-password-1", "bob": "bob-password-1"}
SECRET = "oidc-client-secret-ZZZZ9999"


def init_db():
    with db.conn() as c:
        db.init_shared(c)
        for module in (config, auth, core, ai, admin):
            module.init(c)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(auth, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(p.handle)))
    monkeypatch.setattr(auth, "_cache", {})
    return p


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    init_db()


@pytest.fixture
def app(base, provider, monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-1")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", SECRET)
    with db.conn() as c:
        for name, pw in PASSWORDS.items():
            auth.create_user(c, name, pw, name.title(), f"{name}@example.com", is_admin=name == "root")
    return main.create_app()


def client_for(app, name=None):
    client = TestClient(app, follow_redirects=False)
    if name:
        r = client.post("/api/auth/login", json={"username": name, "password": PASSWORDS[name]})
        assert r.status_code == 200, r.text
    return client


def user(name):
    with db.conn() as c:
        return dict(c.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone())


def set_sub(name, sub):
    with db.conn() as c:
        c.execute("UPDATE users SET oidc_sub=? WHERE username=?", (sub, name))


def log_actions():
    with db.conn() as c:
        return [r["action"] for r in c.execute("SELECT action FROM admin_log ORDER BY id")]


def start_link(client, provider):
    r = client.get("/auth/oidc/link")
    assert r.status_code == 302, r.text
    query = parse_qs(urlsplit(r.headers["location"]).query)
    provider.challenge, provider.nonce = query["code_challenge"][0], query["nonce"][0]
    return query["state"][0]


def callback(client, state):
    return client.get("/auth/oidc/callback", params={"state": state, "code": "good-code"})


def read_session(client) -> dict:
    raw = TimestampSigner(TEST_SECRET_KEY).unsign(client.cookies["macrolog_session"].encode())
    return json.loads(base64.b64decode(raw))


def write_session(client, data: dict) -> None:
    signed = TimestampSigner(TEST_SECRET_KEY).sign(base64.b64encode(json.dumps(data).encode()))
    client.cookies.clear()
    client.cookies.set("macrolog_session", signed.decode())


# ---------------------------------------------------------------- link SSO

def test_link_happy_path_does_not_need_verified_email(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    provider.claims = {"email_verified": False, "email": "someone-else@example.org"}
    r = callback(alice, state)
    assert r.status_code == 302 and r.headers["location"] == "/#settings"
    me = alice.get("/api/auth/me").json()
    assert me["username"] == "alice" and me["sso_linked"] is True and me["has_password"] is True
    assert user("alice")["oidc_sub"] == "sub-1" and user("alice")["email"] == "alice@example.com"
    assert "self.sso_link" in log_actions()
    fresh = client_for(app)  # a later plain SSO sign-in now lands on alice
    r = fresh.get("/auth/oidc/login")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    provider.challenge, provider.nonce = q["code_challenge"][0], q["nonce"][0]
    assert callback(fresh, q["state"][0]).status_code == 302
    assert fresh.get("/api/auth/me").json()["username"] == "alice"


def test_link_requests_carry_session_bound_flow(app, provider):
    alice = client_for(app, "alice")
    start_link(alice, provider)
    flow = read_session(alice)["oidc"]
    assert flow["mode"] == "link" and flow["uid"] == user("alice")["id"] and flow["sv"] == 0


def test_link_needs_a_session(app, provider):
    r = client_for(app).get("/auth/oidc/link")
    assert r.status_code == 401 and "Sign in first" in r.text


def test_link_404_when_sso_unconfigured(app, monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER")
    assert client_for(app, "alice").get("/auth/oidc/link").status_code == 404


def test_link_refuses_cross_site_start(app, provider):
    r = client_for(app, "alice").get("/auth/oidc/link", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403 and user("alice")["oidc_sub"] is None


def test_link_refused_when_already_linked(app, provider):
    set_sub("alice", "old-sub")
    r = client_for(app, "alice").get("/auth/oidc/link")
    assert r.status_code == 409 and "already linked" in r.text


def test_link_refused_when_sub_belongs_to_another_user(app, provider):
    set_sub("bob", "sub-1")
    alice = client_for(app, "alice")
    r = callback(alice, start_link(alice, provider))
    assert r.status_code == 409 and "another Macrolog user" in r.text
    assert user("alice")["oidc_sub"] is None and user("bob")["oidc_sub"] == "sub-1"
    assert alice.get("/api/auth/me").status_code == 200  # still signed in


def test_link_refused_when_linked_during_the_flow(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    set_sub("alice", "other-sub")
    r = callback(alice, state)
    assert r.status_code == 409 and user("alice")["oidc_sub"] == "other-sub"


def test_link_state_tampering(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    r = callback(alice, state + "x")
    assert r.status_code == 400 and "invalid state" in r.text
    assert callback(alice, state).status_code == 400  # flow consumed
    assert user("alice")["oidc_sub"] is None


def test_link_nonce_tampering(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    provider.nonce = "attacker-nonce"
    r = callback(alice, state)
    assert r.status_code == 400 and user("alice")["oidc_sub"] is None


def test_link_finished_by_another_session_user(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    session = read_session(alice)
    bob = user("bob")
    write_session(alice, {**session, "uid": bob["id"], "sv": bob["session_version"]})  # valid bob session
    r = callback(alice, state)
    assert r.status_code == 403 and "session changed" in r.text
    assert user("alice")["oidc_sub"] is None and user("bob")["oidc_sub"] is None


def test_link_flow_dies_when_user_switches_account(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    alice.post("/api/auth/login", json={"username": "bob", "password": PASSWORDS["bob"]})  # clears the session
    assert callback(alice, state).status_code == 400
    assert user("bob")["oidc_sub"] is None and user("alice")["oidc_sub"] is None


def test_link_refused_after_session_revoked(app, provider):
    alice = client_for(app, "alice")
    state = start_link(alice, provider)
    client_for(app, "root").patch(f"/api/admin/users/{user('alice')['id']}", json={"password": "new-password-9"})
    r = callback(alice, state)
    assert r.status_code == 403 and user("alice")["oidc_sub"] is None


def test_link_does_not_leak_client_secret(app, provider, caplog):
    caplog.set_level("DEBUG")
    alice = client_for(app, "alice")
    r = callback(alice, start_link(alice, provider))
    assert SECRET not in r.text and SECRET not in caplog.text


# ---------------------------------------------------------------- unlink

def test_self_unlink(app):
    set_sub("alice", "sub-a")
    alice = client_for(app, "alice")
    r = alice.post("/api/auth/sso/unlink")
    assert r.status_code == 200 and r.json()["sso_linked"] is False
    assert user("alice")["oidc_sub"] is None and "self.sso_unlink" in log_actions()
    assert alice.get("/api/auth/me").status_code == 200
    assert alice.post("/api/auth/sso/unlink").status_code == 409  # not linked any more


def test_self_unlink_needs_password(app, provider):
    with db.conn() as c:
        c.execute("UPDATE users SET password_hash=NULL, oidc_sub='sub-1' WHERE username='alice'")
    client = client_for(app)
    r = client.get("/auth/oidc/login")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    provider.challenge, provider.nonce = q["code_challenge"][0], q["nonce"][0]
    callback(client, q["state"][0])
    assert client.get("/api/auth/me").json()["username"] == "alice"
    r = client.post("/api/auth/sso/unlink")
    assert r.status_code == 409 and "no password" in r.json()["detail"]
    assert user("alice")["oidc_sub"] == "sub-1"


def test_self_unlink_refused_while_local_login_off(app):
    set_sub("alice", "sub-a")
    alice = client_for(app, "alice")
    with db.conn() as c:
        config.store(c, "local_login", "0")
    assert alice.post("/api/auth/sso/unlink").status_code == 409
    assert user("alice")["oidc_sub"] == "sub-a"


def test_self_unlink_cross_origin(app):
    set_sub("alice", "sub-a")
    r = client_for(app, "alice").post("/api/auth/sso/unlink", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and user("alice")["oidc_sub"] == "sub-a"


def test_admin_unlink_sso(app):
    set_sub("alice", "sub-a")
    alice, root = client_for(app, "alice"), client_for(app, "root")
    r = root.patch(f"/api/admin/users/{user('alice')['id']}", json={"unlink_sso": True})
    assert r.status_code == 200 and r.json()["sso_linked"] is False
    assert alice.get("/api/auth/me").status_code == 401  # sessions end with the link
    with db.conn() as c:
        detail = c.execute("SELECT detail FROM admin_log ORDER BY id DESC").fetchone()[0]
    assert detail == "SSO unlinked"
    assert root.patch(f"/api/admin/users/{user('alice')['id']}", json={"unlink_sso": "yes"}).status_code == 400


def test_admin_cannot_unlink_own_sso_into_lockout(app):
    set_sub("root", "sub-r")
    with db.conn() as c:
        c.execute("UPDATE users SET password_hash=NULL WHERE username='root'")
        root_id = user("root")["id"]
        c.execute("UPDATE users SET session_version=0 WHERE id=?", (root_id,))
    root = client_for(app)
    write_session(root, {"uid": root_id, "sv": 0})
    r = root.patch(f"/api/admin/users/{root_id}", json={"unlink_sso": True})
    assert r.status_code == 400 and user("root")["oidc_sub"] == "sub-r"


def test_last_sso_admin_cannot_be_unlinked_while_local_login_off(app):
    set_sub("root", "sub-r")
    root = client_for(app, "root")
    root.patch(f"/api/admin/users/{user('alice')['id']}", json={"is_admin": True})
    alice = client_for(app, "alice")
    with db.conn() as c:
        config.store(c, "local_login", "0")
    r = alice.patch(f"/api/admin/users/{user('root')['id']}", json={"unlink_sso": True})
    assert r.status_code == 409 and user("root")["oidc_sub"] == "sub-r"


# ---------------------------------------------------------------- first-run setup

@pytest.fixture
def empty(base):
    return main.create_app()


def setup_body(name="owner", password="owner-password-1", **extra):
    return {"username": name, "password": password, **extra}


def test_setup_creates_first_admin_and_signs_in(empty):
    client = client_for(empty)
    assert client.get("/api/auth/config").json()["needs_setup"] is True
    r = client.post("/api/auth/setup", json=setup_body(display_name="The Owner"))
    assert r.status_code == 200, r.text
    assert r.json() == {"id": 1, "username": "owner", "display_name": "The Owner", "is_admin": True}
    assert client.get("/api/auth/me").json()["is_admin"] is True
    assert client.get("/api/admin/users").status_code == 200
    assert client.get("/api/auth/config").json()["needs_setup"] is False
    assert "setup.first_admin" in log_actions()
    assert "owner-password-1" not in json.dumps(user("owner"))


def test_setup_is_409_forever_once_a_user_exists(empty):
    client = client_for(empty)
    assert client.post("/api/auth/setup", json=setup_body()).status_code == 200
    other = client_for(empty)
    assert other.post("/api/auth/setup", json=setup_body("intruder")).status_code == 409
    assert other.post("/api/auth/setup", json={"junk": 1}).status_code == 409
    with db.conn() as c:
        assert auth.user_count(c) == 1


def test_setup_409_when_env_bootstrap_created_a_user(base, monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "envadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "env-password-1")
    auth.bootstrap_admin()
    client = client_for(main.create_app())
    assert client.get("/api/auth/config").json()["needs_setup"] is False
    assert client.post("/api/auth/setup", json=setup_body()).status_code == 409
    assert user("envadmin")["is_admin"] == 1


@pytest.mark.parametrize("body", [
    setup_body(password="short"), setup_body(name="bad name!"), setup_body(extra_field=1),
    {"username": "owner"}, setup_body(display_name=5), setup_body(display_name="a\x00b"), "not-an-object", None,
])
def test_setup_validation_never_echoes_password(empty, body):
    r = client_for(empty).post("/api/auth/setup", json=body)
    assert r.status_code == 400
    assert "owner-password-1" not in r.text
    with db.conn() as c:
        assert auth.user_count(c) == 0


def test_setup_same_origin(empty):
    client = client_for(empty)
    assert client.post("/api/auth/setup", json=setup_body(), headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/setup", json=setup_body(), headers={"sec-fetch-site": "cross-site"}).status_code == 403
    with db.conn() as c:
        assert auth.user_count(c) == 0


def test_setup_is_rate_limited(empty):
    client = client_for(empty)
    for _ in range(auth.SETUP_MAX_IP):
        assert client.post("/api/auth/setup", json=setup_body(password="short")).status_code == 400
    r = client.post("/api/auth/setup", json=setup_body())
    assert r.status_code == 429 and "Retry-After" in r.headers
    with db.conn() as c:
        assert auth.user_count(c) == 0


def test_setup_race_creates_exactly_one_admin(empty):
    n = 6
    gate, codes = threading.Barrier(n), []

    def run(i):
        client = client_for(empty)
        gate.wait()
        codes.append(client.post("/api/auth/setup", json=setup_body(f"owner{i}")).status_code)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200] + [409] * (n - 1)
    with db.conn() as c:
        rows = c.execute("SELECT is_admin FROM users").fetchall()
    assert [r[0] for r in rows] == [1]


# ---------------------------------------------------------------- misc

def test_cross_site_fetch_metadata_rejected_on_login(app):
    r = client_for(app).post("/api/auth/login", json={"username": "alice", "password": PASSWORDS["alice"]},
                             headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_admin_config_redirect_uri_null_without_public_url(app, monkeypatch):
    root = client_for(app, "root")
    monkeypatch.delenv("PUBLIC_URL")
    body = root.get("/api/admin/config").json()
    assert body["oidc_redirect_uri"] is None and "PUBLIC_URL" in body["oidc_redirect_uri_warning"]
    text = " ".join(body["authentik_checklist"]).lower()
    for word in ("confidential", "strict", "rs256", "openid", "email", "profile", "id_token"):
        assert word in text


def test_sso_settings_change_clears_discovery_cache(app, provider):
    root = client_for(app, "root")
    auth._cache["x"] = (0.0, {})
    root.put("/api/admin/config", json={"oidc_name": "Home"})
    assert auth._cache == {}


def test_validation_errors_never_echo_submitted_values(app):
    secret = "SECRETPW" * 200  # longer than the password limit
    r = client_for(app).post("/api/auth/login", json={"username": "alice", "password": secret})
    assert r.status_code == 422 and "SECRETPW" not in r.text
    assert r.json()["detail"][0]["loc"] == ["body", "password"]


def test_first_account_becomes_admin_when_no_admin_exists():
    init_db()
    with db.conn() as c:
        first = auth.create_user(c, "first", password="first-password-1")
        second = auth.create_user(c, "second", password="second-password-1")
        flags = {r["id"]: r["is_admin"] for r in c.execute("SELECT id, is_admin FROM users")}
    assert flags[first] == 1
    assert flags[second] == 0
