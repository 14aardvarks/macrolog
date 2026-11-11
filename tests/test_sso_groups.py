"""Group based admin sync at SSO sign-in, the Users screen guard, scopes and the new settings."""
from urllib.parse import parse_qs, urlsplit

import pytest

from app import config
from test_sso_setup import PASSWORDS, app, base, callback, client_for, log_actions, provider, user  # noqa: F401
from app import db

GROUP = "admin"


def sso_login(app, provider, **claims):
    provider.claims = claims
    client = client_for(app)
    r = client.get("/auth/oidc/login")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    provider.challenge, provider.nonce = q["code_challenge"][0], q["nonce"][0]
    r = callback(client, q["state"][0])
    assert r.status_code == 302, r.text
    return client


def link(name, sub="sub-1"):
    with db.conn() as c:
        c.execute("UPDATE users SET oidc_sub=? WHERE username=?", (sub, name))


@pytest.fixture
def grouped(app, monkeypatch):
    monkeypatch.setenv("OIDC_ADMIN_GROUP", GROUP)
    link("alice")
    return app


def log_rows(action):
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM admin_log WHERE action=?", (action,))]


def test_promotes_linked_user(grouped, provider):
    sso_login(grouped, provider, groups=["x", GROUP])
    assert user("alice")["is_admin"] == 1
    rows = log_rows("sso.group_promoted")
    assert len(rows) == 1 and rows[0]["admin_id"] == user("alice")["id"] and GROUP in rows[0]["detail"]


def test_demotes_and_ends_sessions(grouped, provider):
    with db.conn() as c:
        c.execute("UPDATE users SET is_admin=1 WHERE username='alice'")
    sso_login(grouped, provider, groups=["other"])
    assert user("alice")["is_admin"] == 0 and user("alice")["session_version"] == 1
    assert "sso.group_demoted" in log_actions()


def test_last_admin_is_never_demoted(grouped, provider):
    with db.conn() as c:
        c.execute("UPDATE users SET is_admin=0 WHERE username='root'")
        c.execute("UPDATE users SET is_admin=1 WHERE username='alice'")
    sso_login(grouped, provider, groups=[])
    assert user("alice")["is_admin"] == 1
    assert "sso.group_demote_blocked" in log_actions() and "sso.group_demoted" not in log_actions()


def test_missing_claim_changes_nothing(grouped, provider):
    with db.conn() as c:
        c.execute("UPDATE users SET is_admin=1 WHERE username='alice'")
    sso_login(grouped, provider)
    assert user("alice")["is_admin"] == 1
    assert not any(a.startswith("sso.group") for a in log_actions())


def test_off_by_default(app, provider):
    link("alice")
    sso_login(app, provider, groups=[GROUP])
    assert user("alice")["is_admin"] == 0


def test_single_string_claim_and_case_sensitivity(grouped, provider):
    sso_login(grouped, provider, groups=GROUP)
    assert user("alice")["is_admin"] == 1
    with db.conn() as c:
        c.execute("UPDATE users SET is_admin=0 WHERE username='alice'")
    sso_login(grouped, provider, groups=[GROUP.upper()])
    assert user("alice")["is_admin"] == 0


def test_custom_claim_name(grouped, provider, monkeypatch):
    monkeypatch.setenv("OIDC_GROUPS_CLAIM", "roles")
    sso_login(grouped, provider, groups=[GROUP], roles=[])
    assert user("alice")["is_admin"] == 0
    sso_login(grouped, provider, roles=[GROUP])
    assert user("alice")["is_admin"] == 1


def test_falls_back_to_userinfo(grouped, provider):
    provider.userinfo = {"sub": "sub-1", "groups": [GROUP]}
    sso_login(grouped, provider)
    assert user("alice")["is_admin"] == 1


def test_new_signup_gets_group_role(grouped, provider, monkeypatch):
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "1")
    sso_login(grouped, provider, sub="sub-new", preferred_username="newbie", email=None, groups=[GROUP])
    assert user("newbie")["is_admin"] == 1
    sso_login(grouped, provider, sub="sub-other", preferred_username="plain", email=None, groups=["x"])
    assert user("plain")["is_admin"] == 0


def test_log_has_no_tokens_or_claim_dump(grouped, provider):
    sso_login(grouped, provider, groups=["secret-group-zzz", GROUP])
    with db.conn() as c:
        text = " ".join(f"{r['target']} {r['detail']}" for r in c.execute("SELECT * FROM admin_log"))
    assert "secret-group-zzz" not in text and "good-code" not in text


def scope_of(client):
    r = client.get("/auth/oidc/login")
    return parse_qs(urlsplit(r.headers["location"]).query)["scope"][0]


def test_scope(app, monkeypatch):
    assert scope_of(client_for(app)) == "openid email profile"
    monkeypatch.setenv("OIDC_ADMIN_GROUP", GROUP)
    assert scope_of(client_for(app)) == "openid email profile groups"


def test_users_screen_refuses_admin_change_for_sso_users(grouped):
    root = client_for(grouped, "root")
    alice = user("alice")["id"]
    r = root.patch(f"/api/admin/users/{alice}", json={"is_admin": True})
    assert r.status_code == 409 and "managed by the authentik group" in r.json()["detail"]
    assert user("alice")["is_admin"] == 0
    listed = {u["username"]: u for u in root.get("/api/admin/users").json()["users"]}
    assert listed["alice"]["admin_by_group"] is True and listed["bob"]["admin_by_group"] is False
    bob = user("bob")["id"]  # local only account stays manual
    assert root.patch(f"/api/admin/users/{bob}", json={"is_admin": True}).status_code == 200
    assert root.patch(f"/api/admin/users/{alice}", json={"display_name": "Al"}).status_code == 200


def test_users_screen_free_when_feature_off(app):
    link("alice")
    r = client_for(app, "root").patch(f"/api/admin/users/{user('alice')['id']}", json={"is_admin": True})
    assert r.status_code == 200


def test_settings_validation(base):
    assert config.get("oidc_admin_group") == "" and config.get("oidc_groups_claim") == "groups"
    assert config.validate("oidc_admin_group", "  grp  ") == "grp"
    for key in ("oidc_admin_group", "oidc_user_group", "oidc_groups_claim"):
        assert config.validate(key, "x" * 200) == "x" * 200
        with pytest.raises(config.ConfigError):
            config.validate(key, "x" * 201)
    assert config.describe()["oidc_groups_claim"]["value"] == "groups"


def sso_refused(app, provider, **claims):
    provider.claims = claims
    client = client_for(app)
    q = parse_qs(urlsplit(client.get("/auth/oidc/login").headers["location"]).query)
    provider.challenge, provider.nonce = q["code_challenge"][0], q["nonce"][0]
    r = callback(client, q["state"][0])
    assert r.status_code == 403 and "not in the allowed group" in r.text
    assert client.get("/api/auth/me").status_code == 401
    return r


def test_user_group_refuses_outsiders_without_side_effects(app, provider, monkeypatch):
    monkeypatch.setenv("OIDC_USER_GROUP", "user")
    monkeypatch.setenv("OIDC_ADMIN_GROUP", GROUP)
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "1")
    link("alice")
    with db.conn() as c:
        c.execute("UPDATE users SET is_admin=1 WHERE username='alice'")
        before = c.execute("SELECT count(*) FROM users").fetchone()[0]
    sso_refused(app, provider, groups=["other"])  # existing linked admin is refused and not demoted
    assert user("alice")["is_admin"] == 1
    sso_refused(app, provider, sub="sub-new", preferred_username="newbie", email=None, groups=[])
    sso_refused(app, provider, sub="sub-new", preferred_username="newbie", email=None)  # claim missing: fail closed
    with db.conn() as c:
        assert c.execute("SELECT count(*) FROM users").fetchone()[0] == before
    assert not any(a.startswith("sso.group") for a in log_actions())


def test_user_group_allows_members_and_admin_group(app, provider, monkeypatch):
    monkeypatch.setenv("OIDC_USER_GROUP", "user")
    monkeypatch.setenv("OIDC_ADMIN_GROUP", GROUP)
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "1")
    sso_login(app, provider, sub="sub-new", preferred_username="newbie", email=None, groups=["user"])
    assert user("newbie")["is_admin"] == 0
    sso_login(app, provider, sub="sub-adm", preferred_username="boss", email=None, groups=[GROUP])
    assert user("boss")["is_admin"] == 1


def test_user_group_does_not_affect_password_login(app, monkeypatch):
    monkeypatch.setenv("OIDC_USER_GROUP", "user")
    assert client_for(app, "alice").get("/api/auth/me").status_code == 200


def test_user_group_requests_groups_scope(app, monkeypatch):
    monkeypatch.setenv("OIDC_USER_GROUP", "user")
    assert scope_of(client_for(app)) == "openid email profile groups"
