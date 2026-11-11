"""SSO identities are (issuer, subject) pairs, first-user handling, ADMIN_USER safety, numeric overflow."""
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import admin, ai, auth, config, core, db, main

ISSUER = "https://auth.example.com/application/o/macrolog/"
OTHER = "https://other-idp.example/app/"
PW = "root-password-1"


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    init()


def init():
    with db.conn() as c:
        db.init_shared(c)
        for m in (config, auth, core, ai, admin):
            m.init(c)


def sso_env(monkeypatch, issuer=ISSUER):
    monkeypatch.setenv("OIDC_ISSUER", issuer)
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-1")


def mk(name="root", admin_=True, sub=None, iss=None, email=None):
    with db.conn() as c:
        uid = auth.create_user(c, name, PW, email=email, is_admin=admin_)
        c.execute("UPDATE users SET oidc_sub=?, oidc_iss=? WHERE id=?", (sub, iss, uid))
    return uid


def row(name):
    with db.conn() as c:
        return c.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()


def resolve(claims):
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        return auth._resolve_user(c, claims)


def actions():
    with db.conn() as c:
        return [(r["action"], r["admin_id"], r["detail"]) for r in c.execute("SELECT * FROM admin_log ORDER BY id")]


def admin_client():
    cl = TestClient(main.create_app(), follow_redirects=False)
    assert cl.post("/api/auth/login", json={"username": "root", "password": PW}).status_code == 200
    return cl


# ---------------------------------------------------------------- issuer in identity

def test_login_matches_issuer_and_sub(monkeypatch):
    sso_env(monkeypatch)
    mk(sub="s1", iss=OTHER)
    with pytest.raises(auth.OIDCError):  # same sub from another provider is a different identity
        resolve({"sub": "s1", "iss": ISSUER})
    assert resolve({"sub": "s1", "iss": OTHER})["username"] == "root"


def test_null_issuer_matches_current_and_gets_stamped(monkeypatch):
    mk(sub="s1", iss=None)
    sso_env(monkeypatch)
    assert resolve({"sub": "s1", "iss": ISSUER})["username"] == "root"
    assert row("root")["oidc_iss"] == ISSUER


def test_link_allows_same_sub_other_issuer_but_not_same_pair():
    mk("a", sub="s1", iss=OTHER)
    b, c_ = mk("b", False), mk("c", False)
    with db.conn() as c:
        auth._link_sub(c, b, ISSUER, "s1")
    assert row("b")["oidc_iss"] == ISSUER
    with db.conn() as c, pytest.raises(auth.OIDCError) as exc:
        auth._link_sub(c, c_, ISSUER, "s1")
    assert exc.value.status == 409


def test_unique_index_on_the_pair():
    mk("a", sub="s1", iss=ISSUER)
    with pytest.raises(sqlite3.IntegrityError):
        mk("b", sub="s1", iss=ISSUER)


def test_unlink_clears_issuer_self_and_admin(monkeypatch):
    sso_env(monkeypatch)
    mk(sub="s1", iss=ISSUER)
    b = mk("bob", False, sub="s2", iss=ISSUER)
    cl = admin_client()
    assert cl.post("/api/auth/sso/unlink").status_code == 200
    assert row("root")["oidc_sub"] is None and row("root")["oidc_iss"] is None
    assert cl.patch(f"/api/admin/users/{b}", json={"unlink_sso": True}).status_code == 200
    assert row("bob")["oidc_iss"] is None


def test_migration_adds_column_and_backfills_with_configured_issuer(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setenv("DB_PATH", path)
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT,"
                " password_hash TEXT, oidc_sub TEXT UNIQUE, email TEXT, created_at TEXT)")
    old.execute("INSERT INTO users(username, oidc_sub) VALUES ('linked','s1'), ('plain', NULL)")
    old.commit()
    old.close()
    sso_env(monkeypatch)
    init()
    assert row("linked")["oidc_iss"] == ISSUER and row("plain")["oidc_iss"] is None


def test_migration_without_configured_issuer_leaves_null():
    mk(sub="s1")
    init()
    assert row("root")["oidc_iss"] is None


# ---------------------------------------------------------------- lockout guard

def lockout_ready(monkeypatch, iss):
    sso_env(monkeypatch)
    mk(sub="s1", iss=iss)
    with db.conn() as c:
        admin._record_test(c, ISSUER, "client-1", True)


@pytest.mark.parametrize("iss,ok", [(ISSUER, True), (None, True), (OTHER, False)])
def test_lockout_counts_only_admins_on_the_effective_issuer(monkeypatch, iss, ok):
    lockout_ready(monkeypatch, iss)
    with db.conn() as c:
        if ok:
            admin.check_lockout(c, {"local_login": "0"})
        else:
            with pytest.raises(HTTPException) as exc:
                admin.check_lockout(c, {"local_login": "0"})
            assert exc.value.status_code == 409


def test_issuer_switch_while_local_login_off_is_refused(monkeypatch):
    lockout_ready(monkeypatch, ISSUER)
    cl = admin_client()
    with db.conn() as c:
        config.store(c, "local_login", "0")
    r = cl.put("/api/admin/config", json={"oidc_issuer": OTHER})
    assert r.status_code == 409 and "Turn password sign-in on before changing the SSO provider" in r.json()["detail"]
    r = cl.put("/api/admin/config", json={"oidc_issuer": OTHER, "local_login": False})
    assert r.status_code == 409
    assert auth.oidc_issuer() == ISSUER


def test_issuer_switch_with_password_on_pins_old_links(monkeypatch):
    sso_env(monkeypatch)
    mk(sub="s1", iss=None)
    cl = admin_client()
    with db.conn() as c:  # simulate a NULL left behind with no issuer at migration time
        c.execute("UPDATE users SET oidc_iss=NULL")
    r = cl.put("/api/admin/config", json={"oidc_issuer": OTHER})
    assert r.status_code == 200, r.text
    assert row("root")["oidc_iss"] == ISSUER
    monkeypatch.setenv("OIDC_ISSUER", OTHER)
    with pytest.raises(auth.OIDCError):  # the old identity does not carry over to the new provider
        resolve({"sub": "s1", "iss": OTHER})


def test_same_issuer_rewritten_with_slash_is_not_a_switch(monkeypatch):
    lockout_ready(monkeypatch, ISSUER)
    with db.conn() as c:
        config.store(c, "local_login", "0")
        admin.check_lockout(c, {"oidc_issuer": ISSUER.rstrip("/")})


# ---------------------------------------------------------------- ADMIN_USER

def test_admin_user_env_does_not_promote_sso_signup(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "alice")
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "1")
    mk("owner")
    got = resolve({"sub": "x", "preferred_username": "alice"})
    assert got["username"] != "alice" and got["username"].startswith("alice") and not got["is_admin"]
    auth.bootstrap_admin()
    assert not row(got["username"])["is_admin"]


def test_admin_user_env_promotes_only_password_accounts(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "alice")
    mk("alice", False)
    auth.bootstrap_admin()
    assert row("alice")["is_admin"] == 1
    with db.conn() as c:
        c.execute("UPDATE users SET is_admin=0, password_hash=NULL, oidc_sub='s', oidc_iss=NULL")
        c.execute("INSERT INTO users(username, is_admin) VALUES ('keeper', 1)")
    auth.bootstrap_admin()
    assert row("alice")["is_admin"] == 0


# ---------------------------------------------------------------- first account

def test_sso_signup_refused_before_setup_when_password_login_on(monkeypatch):
    sso_env(monkeypatch)
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "1")
    with pytest.raises(auth.OIDCError) as exc:
        resolve({"sub": "s1", "preferred_username": "stranger"})
    assert "Finish first-run setup first" in str(exc.value)
    with db.conn() as c:
        assert auth.user_count(c) == 0
    cl = TestClient(main.create_app())
    assert cl.get("/api/auth/config").json()["needs_setup"] is True
    assert cl.post("/api/auth/setup", json={"username": "owner", "password": "owner-password-1"}).status_code == 200


def test_local_login_off_first_sso_signin_creates_admin(monkeypatch):
    sso_env(monkeypatch)
    monkeypatch.setenv("LOCAL_LOGIN", "0")
    cl = TestClient(main.create_app())
    info = cl.get("/api/auth/config").json()
    assert info["needs_setup"] is False and info["first_admin_via_sso"] is True
    r = cl.post("/api/auth/setup", json={"username": "owner", "password": "owner-password-1"})
    assert r.status_code == 409 and r.json()["detail"] == auth.SETUP_VIA_SSO
    first = resolve({"sub": "s1", "iss": ISSUER, "preferred_username": "boss"})  # oidc_allow_signup is 0
    assert first["is_admin"] == 1 and first["oidc_iss"] == ISSUER
    assert ("setup.first_admin_sso", first["id"], f"issuer {ISSUER}") in actions()
    info = cl.get("/api/auth/config").json()
    assert info["needs_setup"] is False and info["first_admin_via_sso"] is False
    with pytest.raises(auth.OIDCError):  # the next stranger is refused again
        resolve({"sub": "s2", "preferred_username": "other"})


def test_local_login_off_without_sso_still_allows_setup(monkeypatch):
    monkeypatch.setenv("LOCAL_LOGIN", "0")
    cl = TestClient(main.create_app())
    assert cl.get("/api/auth/config").json()["needs_setup"] is True


# ---------------------------------------------------------------- audit and overflow

def test_verified_email_autolink_is_audited(monkeypatch):
    sso_env(monkeypatch)
    uid = mk("bob", False, email="bob@example.com")
    got = resolve({"sub": "s9", "iss": ISSUER, "email": "bob@example.com", "email_verified": True})
    assert got["id"] == uid and row("bob")["oidc_iss"] == ISSUER
    assert ("sso.linked_by_email", uid, f"issuer {ISSUER}") in actions()
    assert "s9" not in repr(actions())


def test_huge_numbers_are_400_not_500():
    mk()
    cl = admin_client()
    for key in ("ai_monthly_cap", "ai_price_in_per_mtok"):
        r = cl.put("/api/admin/config", json={key: 10**400})
        assert r.status_code == 400 and "Unknown" not in r.json()["detail"], key


def test_other_numeric_parsers_survive_huge_ints():
    with pytest.raises(HTTPException) as exc:
        core.number(10**400, "amount")
    assert exc.value.status_code == 400
    assert ai._num(10**400) is None
