import asyncio
import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc.jwk import RSAKey

from app import admin, ai, auth, auth_cli, config, core, db, main

ISSUER = "https://sso.example.com/application/o/macrolog/"
JWKS = ISSUER + "jwks/"
KEY = RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"}, private=True)
SECRETS = {"ai_global_key": "sk-ant-global-secret-AAAA1111", "oidc_client_secret": "oidc-client-secret-BBBB2222",
           "fdc_api_key": "fdc-secret-CCCC3333"}
PERSONAL = "sk-ant-personal-secret-DDDD4444"
PASSWORDS = {"root": "root-password-1", "bob": "bob-password-1", "carol": "carol-password-1"}


class Provider:
    """Discovery and JWKS endpoints with switchable misbehaviour."""

    def __init__(self):
        self.meta = {"issuer": ISSUER, "authorization_endpoint": ISSUER + "authorize/",
                     "token_endpoint": ISSUER + "token/", "jwks_uri": JWKS}
        self.jwks = {"keys": [KEY.as_dict(private=False)]}
        self.mode = "ok"
        self.urls = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if self.mode == "down":
            raise httpx.ConnectError("connection refused")
        if self.mode == "timeout":
            raise httpx.ConnectTimeout("slow")
        if url == ISSUER + ".well-known/openid-configuration":
            if self.mode == "huge":
                return httpx.Response(200, content=b"{" + b" " * (admin.PROBE_MAX_BYTES + 10) + b"}")
            if self.mode == "redirect-away":
                return httpx.Response(302, headers={"location": "https://evil.example/.well-known/openid-configuration"})
            if self.mode == "redirect-same":
                return httpx.Response(302, headers={"location": ISSUER + "moved"})
            return httpx.Response(200, json=self.meta)
        if url == ISSUER + "moved":
            return httpx.Response(200, json=self.meta)
        if url == JWKS:
            return httpx.Response(200, json=self.jwks)
        return httpx.Response(404)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(admin, "_transport", httpx.MockTransport(p.handle))
    return p


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    with db.conn() as c:
        db.init_shared(c)
        for module in (config, auth, core, ai, admin):
            module.init(c)
        for name, pw in PASSWORDS.items():
            auth.create_user(c, name, pw, name.title(), f"{name}@example.com")
        c.execute("UPDATE users SET is_admin=1 WHERE username='root'")
    return main.create_app()


def signed_in(app, name):
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"username": name, "password": PASSWORDS[name]})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def root(app):
    return signed_in(app, "root")


@pytest.fixture
def bob(app):
    return signed_in(app, "bob")


def uid(name):
    with db.conn() as c:
        return c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]


def link_sso(name):
    with db.conn() as c:
        c.execute("UPDATE users SET oidc_sub=? WHERE username=?", ("sub-" + name, name))


def entries():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM admin_log ORDER BY id")]


# ---------------------------------------------------------------- access control

def admin_routes():
    for route in admin.router.routes:
        for method in route.methods:
            yield method, route.path.replace("{user_id}", "1")


def test_every_admin_route_is_401_anonymous_and_403_for_users(app, bob):
    anon = TestClient(app)
    routes = list(admin_routes())
    assert len(routes) == 7
    for method, path in routes:
        assert anon.request(method, path, json={}).status_code == 401, (method, path)
        assert bob.request(method, path, json={}).status_code == 403, (method, path)


def test_admin_routes_reject_cross_origin(root):
    r = root.put("/api/admin/config", json={"ai_model": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert root.get("/api/admin/config").json()["settings"]["ai_model"]["value"] == ""


def test_me_includes_role_and_key_flags(root, bob):
    assert root.get("/api/auth/me").json() == {"id": uid("root"), "username": "root", "display_name": "Root",
                                               "is_admin": True, "use_global_ai": True, "personal_key_set": False,
                                               "sso_linked": False, "has_password": True}
    bob.put("/api/ai/key", json={"key": PERSONAL})
    me = bob.get("/api/auth/me").json()
    assert me["is_admin"] is False and me["personal_key_set"] is True and PERSONAL not in json.dumps(me)


def test_bootstrap_marks_admin_user(app, monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "Carol")
    auth.bootstrap_admin()
    with db.conn() as c:
        admins = [r[0] for r in c.execute("SELECT username FROM users WHERE is_admin=1 ORDER BY id")]
    assert admins == ["root", "carol"]


def test_bootstrap_first_user_created_as_admin(monkeypatch):
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)
    monkeypatch.setenv("ADMIN_USER", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-password")
    auth.bootstrap_admin()
    with db.conn() as c:
        assert c.execute("SELECT username, is_admin FROM users").fetchall()[0][:] == ("boss", 1)


# ---------------------------------------------------------------- users

def test_list_users_shape(root, bob):
    bob.put("/api/ai/key", json={"key": PERSONAL})
    link_sso("carol")
    users = {u["username"]: u for u in root.get("/api/admin/users").json()["users"]}
    assert set(users["bob"]) == {"id", "username", "display_name", "email", "is_admin", "disabled", "use_global_ai",
                                 "has_password", "sso_linked", "admin_by_group", "personal_key_set", "created_at"}
    assert users["bob"]["personal_key_set"] is True and users["root"]["personal_key_set"] is False
    assert users["carol"]["sso_linked"] is True and users["bob"]["sso_linked"] is False
    assert users["root"]["is_admin"] is True and users["bob"]["has_password"] is True
    text = root.get("/api/admin/users").text
    assert "scrypt" not in text and PERSONAL not in text


def test_create_user(app, root):
    r = root.post("/api/admin/users", json={"username": " Dave ", "password": "dave-password", "display_name": "Dave D",
                                            "email": "dave@example.com", "is_admin": True})
    assert r.status_code == 200, r.text
    assert (r.json()["username"], r.json()["is_admin"], r.json()["display_name"]) == ("dave", True, "Dave D")
    PASSWORDS["dave"] = "dave-password"
    try:
        assert signed_in(app, "dave").get("/api/admin/users").status_code == 200
    finally:
        del PASSWORDS["dave"]


@pytest.mark.parametrize("body,status", [
    ({"username": "BOB", "password": "long-enough"}, 409),
    ({"username": "new", "password": "short"}, 400),
    ({"username": "bad name!", "password": "long-enough"}, 400),
    ({"username": "x" * 65, "password": "long-enough"}, 400),
    ({"username": "new"}, 400),
    ({"username": "new", "password": "long-enough", "role": "god"}, 400),
    ({"username": "new", "password": "long-enough", "is_admin": "yes"}, 400),
    ({"username": "new", "password": "long-enough", "email": "not an email"}, 400),
    ({"username": "new", "password": "long-enough", "display_name": "d" * 101}, 400),
    ({"username": 5, "password": "long-enough"}, 400),
    (["not", "an", "object"], 400),
])
def test_create_user_validation(root, body, status):
    r = root.post("/api/admin/users", json=body)
    assert r.status_code == status, r.text
    assert "long-enough" not in r.text and "short" not in r.text.replace("characters", "")


def test_patch_user_fields(root):
    r = root.patch(f"/api/admin/users/{uid('bob')}", json={"display_name": "Robert", "email": "",
                                                          "use_global_ai": False, "is_admin": True})
    assert r.status_code == 200, r.text
    u = r.json()
    assert (u["display_name"], u["email"], u["use_global_ai"], u["is_admin"]) == ("Robert", None, False, True)
    assert root.patch("/api/admin/users/9999", json={"disabled": True}).status_code == 404
    assert root.patch(f"/api/admin/users/{uid('bob')}", json={"disabled": "yes"}).status_code == 400
    assert root.patch(f"/api/admin/users/{uid('bob')}", json={"username": "x"}).status_code == 400


def test_password_reset_ends_sessions_and_never_echoes(app, root, bob):
    r = root.patch(f"/api/admin/users/{uid('bob')}", json={"password": "brand-new-pass"})
    assert r.status_code == 200 and "brand-new-pass" not in r.text
    assert bob.get("/api/auth/me").status_code == 401
    bad = root.patch(f"/api/admin/users/{uid('bob')}", json={"password": "tiny"})
    assert bad.status_code == 400 and "tiny" not in bad.text
    assert TestClient(app).post("/api/auth/login", json={"username": "bob", "password": "brand-new-pass"}).status_code == 200


def test_disable_blocks_login_and_kills_session(app, root, bob):
    assert root.patch(f"/api/admin/users/{uid('bob')}", json={"disabled": True}).json()["disabled"] is True
    assert bob.get("/api/auth/me").status_code == 401
    assert bob.get("/api/day").status_code == 401
    r = TestClient(app).post("/api/auth/login", json={"username": "bob", "password": PASSWORDS["bob"]})
    assert r.status_code == 403 and "disabled" in r.json()["detail"]
    root.patch(f"/api/admin/users/{uid('bob')}", json={"disabled": False})
    assert signed_in(app, "bob").get("/api/auth/me").status_code == 200


def test_disabled_flag_alone_blocks_even_with_matching_session_version(bob):
    with db.conn() as c:
        c.execute("UPDATE users SET disabled=1 WHERE username='bob'")  # no version bump
    assert bob.get("/api/auth/me").status_code == 401


def test_demotion_ends_sessions(app, root):
    root.patch(f"/api/admin/users/{uid('bob')}", json={"is_admin": True})
    bob = signed_in(app, "bob")
    assert bob.get("/api/admin/users").status_code == 200
    root.patch(f"/api/admin/users/{uid('bob')}", json={"is_admin": False})
    assert bob.get("/api/auth/me").status_code == 401
    assert signed_in(app, "bob").get("/api/admin/users").status_code == 403


def test_last_admin_guards(app, root):
    me = uid("root")
    r = root.patch(f"/api/admin/users/{me}", json={"is_admin": False})
    assert r.status_code == 409 and "last active administrator" in r.json()["detail"]
    r = root.patch(f"/api/admin/users/{me}", json={"disabled": True})
    assert r.status_code == 400 and "your own account" in r.json()["detail"]
    # a disabled admin does not count as an active one
    root.patch(f"/api/admin/users/{uid('bob')}", json={"is_admin": True})
    root.patch(f"/api/admin/users/{uid('bob')}", json={"disabled": True})
    assert root.patch(f"/api/admin/users/{me}", json={"is_admin": False}).status_code == 409
    # with another active admin, demoting yourself works (and ends your session)
    root.patch(f"/api/admin/users/{uid('carol')}", json={"is_admin": True})
    carol = signed_in(app, "carol")
    assert root.patch(f"/api/admin/users/{me}", json={"is_admin": False}).status_code == 200
    assert root.get("/api/auth/me").status_code == 401
    r = carol.patch(f"/api/admin/users/{uid('carol')}", json={"is_admin": False})
    assert r.status_code == 409
    with db.conn() as c:
        assert auth.active_admin_count(c) == 1


def test_concurrent_demotions_keep_one_admin(app, root):
    root.patch(f"/api/admin/users/{uid('bob')}", json={"is_admin": True})
    bob = signed_in(app, "bob")
    gate, codes = threading.Barrier(2), []

    def run(client, target):
        gate.wait()
        codes.append(client.patch(f"/api/admin/users/{uid(target)}", json={"is_admin": False}).status_code)

    threads = [threading.Thread(target=run, args=(root, "bob")), threading.Thread(target=run, args=(bob, "root"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with db.conn() as c:
        assert auth.active_admin_count(c) == 1
    assert sorted(codes) in ([200, 401], [200, 409], [200, 403])


# ---------------------------------------------------------------- config

def test_get_config_shape(root, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "env-model")
    body = root.get("/api/admin/config").json()
    assert set(body) == {"settings", "environment", "oidc_test", "warnings", "oidc_redirect_uri",
                         "oidc_redirect_uri_warning", "authentik_checklist"}
    assert body["oidc_redirect_uri"] == "http://testserver/auth/oidc/callback"
    assert body["oidc_redirect_uri_warning"] is None
    assert all(isinstance(x, str) for x in body["authentik_checklist"])
    s = body["settings"]
    assert set(s) == set(config.MANAGED)
    assert s["ai_model"] == {"value": "env-model", "source": "environment", "env": "AI_MODEL", "type": "str"}
    assert s["local_login"] == {"value": True, "source": "default", "env": "LOCAL_LOGIN", "type": "bool"}
    assert s["ai_monthly_cap"]["value"] == 100 and s["ai_price_in_per_mtok"]["value"] is None
    assert s["fdc_api_key"] == {"set": False, "unreadable": False, "source": "default", "env": "FDC_API_KEY",
                                "type": "secret"}
    env = body["environment"]
    assert env["SECRET_KEY"] == {"set": True} and env["PUBLIC_URL"] == "http://testserver"
    assert env["TRUST_PROXY"] is False and env["COOKIE_SECURE"] is False and env["DB_PATH"]
    assert "restart" in env["note"]
    assert body["oidc_test"] is None and body["warnings"] == []


def test_put_config_applies_live(root, bob):
    r = root.put("/api/admin/config", json={"ai_model": "claude-live", "ai_monthly_cap": 7, "oidc_name": "Home SSO",
                                            "ai_price_in_per_mtok": 1, "ai_price_out_per_mtok": 5})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["ai_model"] == {"value": "claude-live", "source": "database", "env": "AI_MODEL",
                                                "type": "str"}
    st = bob.get("/api/ai/status").json()
    assert (st["model"], st["price_known"]) == ("claude-live", True)
    assert bob.get("/api/auth/config").json()["oidc_name"] == "Home SSO"
    root.put("/api/admin/config", json={"ai_model": None})
    assert bob.get("/api/ai/status").json()["model"] == ai.DEFAULT_MODEL


@pytest.mark.parametrize("body", [
    {"ai_monthly_cap": -1}, {"ai_monthly_cap": 10**9}, {"ai_price_in_per_mtok": -1}, {"oidc_issuer": "ftp://x/"},
    {"unknown_key": 1}, {"SECRET_KEY": "x" * 40}, {"PUBLIC_URL": "https://x"}, {"local_login": "maybe"}, {}, [1],
])
def test_put_config_validation(root, body):
    r = root.put("/api/admin/config", json=body)
    assert r.status_code == 400, r.text


def test_put_config_is_all_or_nothing(root):
    r = root.put("/api/admin/config", json={"ai_model": "should-not-stick", "ai_monthly_cap": -5})
    assert r.status_code == 400
    assert root.get("/api/admin/config").json()["settings"]["ai_model"]["value"] == ""


def test_secrets_never_leave_the_server(app, root, bob, provider, caplog):
    caplog.set_level("DEBUG")
    r = root.put("/api/admin/config", json=SECRETS)
    assert r.status_code == 200
    for key in SECRETS:
        assert r.json()["settings"][key] == {"set": True, "unreadable": False, "source": "database",
                                             "env": config.MANAGED[key].env, "type": "secret"}
    bob.put("/api/ai/key", json={"key": PERSONAL})
    bad = root.put("/api/admin/config", json={"ai_global_key": "with space " + SECRETS["ai_global_key"]})
    assert bad.status_code == 400
    texts = [r.text, bad.text]
    for client in (root, bob):
        for path in ("/api/admin/config", "/api/admin/users", "/api/admin/log", "/api/ai/status", "/api/auth/me",
                     "/api/auth/config"):
            texts.append(client.get(path).text)
    texts.append(root.post("/api/admin/oidc/test", json={"issuer": ISSUER, "client_id": "c1"}).text)
    texts.append(bob.delete("/api/ai/key").text)
    with db.conn() as c:
        texts.append(json.dumps([dict(r) for r in c.execute("SELECT * FROM admin_log")]))
        texts.append(json.dumps([dict(r) for r in c.execute("SELECT * FROM app_config")]))
    blob = "\n".join(texts) + "\n" + caplog.text
    for secret in [*SECRETS.values(), PERSONAL]:
        assert secret not in blob


def test_cleared_secret_and_null(root, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-anthropic-key-0000000")
    s = root.put("/api/admin/config", json={"ai_global_key": ""}).json()["settings"]["ai_global_key"]
    assert (s["set"], s["source"]) == (False, "database")
    s = root.put("/api/admin/config", json={"ai_global_key": None}).json()["settings"]["ai_global_key"]
    assert (s["set"], s["source"]) == (True, "environment")


def test_wrong_secret_key_surfaces_warning(root, monkeypatch, caplog):
    root.put("/api/admin/config", json={"oidc_client_secret": SECRETS["oidc_client_secret"]})
    monkeypatch.setenv("SECRET_KEY", "rotated-secret-key-rotated-secret-key-000")
    r = root.get("/api/admin/config")  # the running app keeps its cookie key, only the store sees the change
    item = r.json()["settings"]["oidc_client_secret"]
    assert item["unreadable"] is True and item["set"] is False and item["source"] == "default"
    assert any("could not be decrypted" in w for w in r.json()["warnings"])
    assert SECRETS["oidc_client_secret"] not in r.text + caplog.text


# ---------------------------------------------------------------- OIDC test

def run_test(root, **body):
    r = root.post("/api/admin/oidc/test", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_oidc_test_success_records(root, provider):
    res = run_test(root, issuer=ISSUER.rstrip("/"), client_id="client-1")
    assert res["ok"] is True and "look good" in res["message"]
    rec = root.get("/api/admin/config").json()["oidc_test"]
    assert (rec["issuer"], rec["client_id"], rec["matches_current"]) == (ISSUER, "client-1", False)
    root.put("/api/admin/config", json={"oidc_issuer": ISSUER, "oidc_client_id": "client-1"})
    assert root.get("/api/admin/config").json()["oidc_test"]["matches_current"] is True


def test_oidc_test_uses_current_settings(root, provider, monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "env-client")
    assert run_test(root)["ok"] is True
    assert root.get("/api/admin/config").json()["oidc_test"]["matches_current"] is True


def test_oidc_test_issuer_mismatch(root, provider):
    provider.meta["issuer"] = "https://sso.example.com/application/o/other/"
    res = run_test(root, issuer=ISSUER, client_id="c")
    assert res["ok"] is False and "mismatch" in res["message"] and "other" in res["message"]
    assert root.get("/api/admin/config").json()["oidc_test"] is None


@pytest.mark.parametrize("mode,text", [
    ("down", "could not be reached"), ("timeout", "timed out"), ("huge", "larger than 1 MB"),
    ("redirect-away", "different host"),
])
def test_oidc_test_failures(root, provider, mode, text):
    provider.mode = mode
    res = run_test(root, issuer=ISSUER, client_id="c")
    assert res["ok"] is False and text in res["message"], res
    assert not any("evil.example" in u for u in provider.urls)


def test_oidc_test_follows_same_host_redirect(root, provider):
    provider.mode = "redirect-same"
    assert run_test(root, issuer=ISSUER, client_id="c")["ok"] is True


def test_oidc_test_oversized_by_content_length(root, provider, monkeypatch):
    monkeypatch.setattr(admin, "PROBE_MAX_BYTES", 10)
    res = run_test(root, issuer=ISSUER, client_id="c")
    assert res["ok"] is False and "larger than 1 MB" in res["message"]


@pytest.mark.parametrize("change,text", [
    (lambda p: p.jwks.update(keys=[]), "no signing keys"),
    (lambda p: p.jwks.update(keys=[{"kty": "bogus"}]), "could not be parsed"),
    (lambda p: p.meta.pop("token_endpoint"), "missing token_endpoint"),
    (lambda p: p.meta.update(jwks_uri="file:///etc/passwd"), "not an http"),
])
def test_oidc_test_bad_documents(root, provider, change, text):
    change(provider)
    res = run_test(root, issuer=ISSUER, client_id="c")
    assert res["ok"] is False and text in res["message"]


def test_oidc_test_slow_drip_is_cut_off(root, provider, monkeypatch):
    monkeypatch.setattr(admin, "PROBE_TIMEOUT", 0.2)

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.sleep(5)
            yield b"}"

    async def handler(request):
        return httpx.Response(200, stream=Slow())

    monkeypatch.setattr(admin, "_transport", httpx.MockTransport(handler))
    res = run_test(root, issuer=ISSUER, client_id="c")
    assert res["ok"] is False and "timed out" in res["message"]


def test_oidc_test_input_validation(root, provider):
    assert root.post("/api/admin/oidc/test", json={"issuer": "gopher://x/", "client_id": "c"}).status_code == 400
    assert root.post("/api/admin/oidc/test", json={"other": 1}).status_code == 400
    assert run_test(root, issuer=ISSUER)["ok"] is False  # no client id configured
    assert provider.urls == []


def test_failed_retest_clears_record(root, provider):
    assert run_test(root, issuer=ISSUER, client_id="c")["ok"] is True
    provider.mode = "down"
    assert run_test(root, issuer=ISSUER, client_id="c")["ok"] is False
    assert root.get("/api/admin/config").json()["oidc_test"] is None


# ---------------------------------------------------------------- lockout safeguards

def sso_ready(root, provider):
    assert root.put("/api/admin/config", json={"oidc_issuer": ISSUER, "oidc_client_id": "client-1"}).status_code == 200
    assert run_test(root)["ok"] is True


def test_local_login_off_needs_test_and_sso_admin(root, provider):
    r = root.put("/api/admin/config", json={"local_login": False})
    assert r.status_code == 409 and "blank" in r.json()["detail"]
    root.put("/api/admin/config", json={"oidc_issuer": ISSUER, "oidc_client_id": "client-1"})
    r = root.put("/api/admin/config", json={"local_login": False})
    assert r.status_code == 409 and "SSO test" in r.json()["detail"]
    assert run_test(root)["ok"] is True
    r = root.put("/api/admin/config", json={"local_login": False})
    assert r.status_code == 409 and "signed in with single sign-on" in r.json()["detail"]
    link_sso("bob")  # a linked non-admin does not count
    assert root.put("/api/admin/config", json={"local_login": False}).status_code == 409
    link_sso("root")
    r = root.put("/api/admin/config", json={"local_login": False})
    assert r.status_code == 200 and r.json()["settings"]["local_login"]["value"] is False
    assert root.get("/api/auth/config").json()["local"] is False


def test_local_login_off_needs_public_url(root, provider, monkeypatch):
    sso_ready(root, provider)
    link_sso("root")
    monkeypatch.delenv("PUBLIC_URL")
    r = root.put("/api/admin/config", json={"local_login": False})
    assert r.status_code == 409 and "PUBLIC_URL" in r.json()["detail"]


def test_cannot_blank_or_change_sso_while_local_login_off(root, provider):
    sso_ready(root, provider)
    link_sso("root")
    assert root.put("/api/admin/config", json={"local_login": False}).status_code == 200
    for body in ({"oidc_client_id": ""}, {"oidc_client_id": None}):
        r = root.put("/api/admin/config", json=body)
        assert r.status_code == 409 and "blank" in r.json()["detail"], body
    for body in ({"oidc_issuer": ""}, {"oidc_issuer": None}):  # the provider itself cannot change
        r = root.put("/api/admin/config", json=body)
        assert r.status_code == 409 and "before changing the SSO provider" in r.json()["detail"], body
    r = root.put("/api/admin/config", json={"oidc_client_id": "untested-client"})
    assert r.status_code == 409 and "SSO test" in r.json()["detail"]
    # unrelated settings still save, and turning password sign-in back on is always allowed
    assert root.put("/api/admin/config", json={"ai_model": "m"}).status_code == 200
    assert root.put("/api/admin/config", json={"local_login": True, "oidc_issuer": ""}).status_code == 409
    assert root.put("/api/admin/config", json={"local_login": True}).status_code == 200
    assert root.put("/api/admin/config", json={"oidc_issuer": ""}).status_code == 200


def test_null_local_login_reverting_to_env_off_is_guarded(root, monkeypatch):
    monkeypatch.setenv("LOCAL_LOGIN", "0")
    root.put("/api/admin/config", json={"local_login": True})
    r = root.put("/api/admin/config", json={"local_login": None})
    assert r.status_code == 409


def test_last_sso_admin_protected_while_local_login_off(app, root, provider):
    sso_ready(root, provider)
    link_sso("root")
    root.patch(f"/api/admin/users/{uid('bob')}", json={"is_admin": True})
    assert root.put("/api/admin/config", json={"local_login": False}).status_code == 200
    r = signed_in_sso_admin_bob(app).patch(f"/api/admin/users/{uid('root')}", json={"disabled": True})
    assert r.status_code == 409 and "single sign-on" in r.json()["detail"]


def signed_in_sso_admin_bob(app):
    # password sign-in is off now, so fake bob's session the way a real login would set it
    from itsdangerous import TimestampSigner
    import base64
    data = base64.b64encode(json.dumps({"uid": uid("bob"), "sv": 1}).encode())
    with db.conn() as c:
        c.execute("UPDATE users SET session_version=1 WHERE username='bob'")
    client = TestClient(app)
    client.cookies.set("macrolog_session", TimestampSigner(main.os.environ["SECRET_KEY"]).sign(data).decode())
    assert client.get("/api/auth/me").json()["is_admin"] is True
    return client


# ---------------------------------------------------------------- audit log

def test_admin_log_records_writes_without_secrets(root, provider):
    root.post("/api/admin/users", json={"username": "erin", "password": "erin-password-9"})
    root.patch(f"/api/admin/users/{uid('erin')}", json={"password": "erin-password-10", "disabled": True})
    root.put("/api/admin/config", json={"ai_model": "claude-y", **SECRETS})
    root.put("/api/admin/config", json={"fdc_api_key": "", "ai_model": None})
    run_test(root, issuer=ISSUER, client_id="c")
    log = root.get("/api/admin/log").json()["entries"]
    assert [e["action"] for e in log] == ["oidc.test", "config.update", "config.update", "user.update", "user.create"]
    assert all(e["admin_username"] == "root" and e["admin_id"] == uid("root") and e["at"] for e in log)
    assert log[4]["target"].startswith("erin (id ")
    assert log[3]["detail"] == "disabled=true, password reset"
    assert "ai_model=claude-y" in log[2]["detail"] and "ai_global_key: set" in log[2]["detail"]
    assert log[1]["detail"] == "fdc_api_key: cleared; ai_model: removed override"
    assert (log[0]["target"], log[0]["detail"]) == (ISSUER, "passed")
    blob = json.dumps(log)
    for secret in [*SECRETS.values(), "erin-password-9", "erin-password-10"]:
        assert secret not in blob


def test_admin_log_limited_to_50(root):
    with db.conn() as c:
        for i in range(60):
            admin.log_action(c, None, "test", str(i))
    log = root.get("/api/admin/log").json()["entries"]
    assert len(log) == 50 and log[0]["target"] == "59" and log[0]["admin_username"] is None


def test_reads_are_not_logged(root):
    root.get("/api/admin/config")
    root.get("/api/admin/users")
    assert entries() == []


# ---------------------------------------------------------------- CLI

def test_cli_admin_commands(app, capsys):
    assert auth_cli.main(["make-admin", "Bob"]) == 0
    assert auth_cli.main(["remove-admin", "root"]) == 0
    assert auth_cli.main(["remove-admin", "bob"]) == 1
    assert "last active administrator" in capsys.readouterr().err
    assert auth_cli.main(["disable-user", "bob"]) == 1  # bob is the only admin left
    assert auth_cli.main(["disable-user", "carol"]) == 0
    assert auth_cli.main(["enable-user", "carol"]) == 0
    assert auth_cli.main(["make-admin", "nobody"]) == 1
    capsys.readouterr()
    assert auth_cli.main(["list-users"]) == 0
    out = capsys.readouterr().out
    assert "\tadmin\tdisabled" in out and "bob\tBob\tbob@example.com\tpassword\t-\tadmin\t-" in out
    assert [e["action"] for e in entries()] == ["cli.make-admin", "cli.remove-admin", "cli.disable-user",
                                                "cli.enable-user"]


def test_cli_unset_config_recovers_from_lockout(app, root, capsys, monkeypatch):
    with db.conn() as c:
        config.store(c, "local_login", "0")  # as if stored while SSO worked
    assert auth.local_enabled() is False
    assert auth_cli.main(["unset-config", "local_login"]) == 0
    assert "environment value or default applies" in capsys.readouterr().out
    assert auth.local_enabled() is True
    with pytest.raises(SystemExit):
        auth_cli.main(["unset-config", "SECRET_KEY"])


@pytest.mark.parametrize("content,ctype", [
    ('{"ai_global_key": "%s"', "application/json"), ('["%s"]', "application/json"),
    ('{"ai_global_key": "%s"}', "text/plain"), ("%s", "text/plain"),
])
def test_malformed_bodies_never_echo_secrets(root, content, ctype):
    secret = SECRETS["ai_global_key"]
    for path in ("/api/admin/config", "/api/ai/key"):
        r = root.put(path, content=content % secret, headers={"content-type": ctype})
        assert r.status_code in (400, 422) and secret not in r.text
    r = root.post("/api/admin/users", content='{"username": "z", "password": "%s"' % secret,
                  headers={"content-type": "application/json"})
    assert r.status_code == 422 and secret not in r.text
