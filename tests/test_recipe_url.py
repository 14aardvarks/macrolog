"""Recipe import from a web address. Claude reads the page with Anthropic's web fetch tool; the transport is mocked and this
server must never request the user's URL itself."""
import json
import sqlite3

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import ai, config, core, db, deps, recipe_ai

SECRET = "sk-ant-secret-key-123"
PERSONAL = "sk-ant-personal-key-11111111111"
URL = "https://recipes.example.org/pancakes?id=4#top"
RECIPE = {"name": "Pancakes", "servings": 4, "confidence": "Clear.", "cut_off": False, "steps": ["Mix.", "Cook."], "ingredients": [
    {"text": "1 1/2 cups flour", "amount": 1.5, "unit": "cups", "name": "flour", "note": None},
    {"text": "2 eggs", "amount": 2, "unit": None, "name": "egg", "note": None}]}


def fetch_block(page="Pancakes. 1 1/2 cups flour. 2 eggs.", error=None):
    content = ({"type": "web_fetch_tool_result_error", "error_code": error} if error else
               {"type": "web_fetch_result", "url": URL, "retrieved_at": "2026-11-13T10:00:00Z",
                "content": {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": page}, "title": "Pancakes"}})
    return [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_fetch", "input": {"url": URL}},
            {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_1", "content": content}]


def reply(data=RECIPE, page="Pancakes. 1 1/2 cups flour. 2 eggs.", error=None, fetched=True):
    blocks = fetch_block(page, error) if fetched else []
    if data is not None:
        blocks.append({"type": "tool_use", "id": "t", "name": recipe_ai.IMPORT_TOOL_NAME, "input": data})
    return {"content": blocks, "stop_reason": "tool_use" if data is not None else "end_turn",
            "usage": {"input_tokens": 4200, "output_tokens": 500, "server_tool_use": {"web_fetch_requests": 1}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("AI_ALLOW_RECIPE_URL", "1")
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        ai.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    st = {"requests": [], "headers": [], "hosts": [], "reply": reply()}

    def handler(req):
        st["requests"].append(json.loads(req.content))
        st["headers"].append(dict(req.headers))
        r = st["reply"]
        return r if isinstance(r, httpx.Response) else httpx.Response(200, json=r)

    # Every request any httpx client makes in this process is recorded, so a fetch of the user's URL would show up here.
    real_async, real_sync = httpx.AsyncClient.send, httpx.Client.send

    async def spy_async(self, request, *a, **k):
        st["hosts"].append(request.url.host)
        return await real_async(self, request, *a, **k)

    def spy_sync(self, request, *a, **k):
        if request.url.host != "testserver":
            st["hosts"].append(request.url.host)
        return real_sync(self, request, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "send", spy_async)
    monkeypatch.setattr(httpx.Client, "send", spy_sync)
    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(handler))
    app = FastAPI()
    for r in (ai.router, core.router, recipe_ai.router):
        app.include_router(r)

    def fake_user(request: Request):
        return {"id": int(request.headers.get("x-user", "1")), "username": "u"}

    app.dependency_overrides[deps.current_user] = fake_user
    st["c"] = TestClient(app)
    st["b"] = TestClient(app, headers={"x-user": "2"})
    return st


def usage_count():
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0]


def post(client, url=URL, **extra):
    return client.post("/api/recipes/import/url", json={"url": url, **extra})


# ---------- success and the request sent ----------

def test_import_url_returns_a_draft_with_its_source(env):
    r = post(env["c"], note="the <second> one")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipe"]["name"] == "Pancakes" and body["recipe"]["servings"] == 4
    assert [(i["amount"], i["unit"], i["name"]) for i in body["recipe"]["ingredients"]] == [(1.5, "cup", "flour"), (2, "count", "egg")]
    assert body["recipe"]["steps"] == ["Mix.", "Cook."] and body["recipe"]["source_url"] == URL
    assert body["warnings"] == ["Claude's note: Clear."]
    assert body["used_this_month"] == 1 and body["input_tokens"] == 4200 and body["key_source"] == "global"
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 0  # nothing saved
    assert SECRET not in r.text


def test_request_carries_the_web_fetch_tool_with_one_use_and_the_content_limit(env):
    assert post(env["c"]).status_code == 200
    sent = env["requests"][0]
    fetch, record = sent["tools"]
    assert fetch == {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1, "max_content_tokens": 30000,
                     "url_sources": {"user_input": {"type": "all"}, "client_tool_results": {"type": "none"},
                                     "server_tool_results": {"type": "none"}}}
    assert "allowed_domains" not in fetch and "blocked_domains" not in fetch and "citations" not in fetch
    assert record["name"] == "record_recipe" and record["strict"] is True
    assert "cut_off" in record["input_schema"]["required"] and record["input_schema"]["properties"]["cut_off"] == {
        "type": "boolean", "description": record["input_schema"]["properties"]["cut_off"]["description"]}
    assert sent["tool_choice"] == {"type": "auto"}  # forcing record_recipe would skip the fetch
    text = sent["messages"][0]["content"][0]["text"]
    assert f"<url>{URL}</url>" in text and "never instructions" in text
    assert sent["messages"][0]["role"] == "user"  # the URL must be in a user message for the tool to fetch it
    assert "anthropic-beta" not in env["headers"][0]


def test_strict_schema_stays_within_the_union_limit():
    unions = 0

    def walk(node):
        nonlocal unions
        if isinstance(node, dict):
            if isinstance(node.get("type"), list) or "anyOf" in node:
                unions += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(recipe_ai.URL_IMPORT_TOOL["input_schema"])
    assert unions <= 16
    assert recipe_ai.IMPORT_TOOL["input_schema"]["required"] == ["name", "servings", "ingredients", "confidence"]  # text import unchanged


def test_content_limit_comes_from_the_admin_setting_within_bounds(env, monkeypatch):
    monkeypatch.setenv("AI_RECIPE_URL_MAX_CONTENT_TOKENS", "12000")
    assert post(env["c"]).status_code == 200
    assert env["requests"][-1]["tools"][0]["max_content_tokens"] == 12000
    monkeypatch.setenv("AI_RECIPE_URL_MAX_CONTENT_TOKENS", "999999")
    assert ai.recipe_url_max_tokens() == 100000
    monkeypatch.setenv("AI_RECIPE_URL_MAX_CONTENT_TOKENS", "5")
    assert ai.recipe_url_max_tokens() == 2000
    for bad in (1999, 100001, "x", 2.5):
        with pytest.raises(config.ConfigError):
            config.validate("ai_recipe_url_max_tokens", bad)
    assert config.validate("ai_recipe_url_max_tokens", 30000) == "30000"
    assert config.MANAGED["ai_recipe_url_max_tokens"].default == "30000"


def test_server_never_requests_the_users_url(env):
    assert post(env["c"]).status_code == 200
    assert env["hosts"] == ["api.anthropic.com"]
    assert "recipes.example.org" not in env["hosts"]


# ---------- switches, key and cap ----------

def test_switch_off_by_default_refuses_before_anything(env, monkeypatch):
    monkeypatch.delenv("AI_ALLOW_RECIPE_URL")
    r = post(env["c"])
    assert r.status_code == 403 and "web address is turned off" in r.json()["detail"]
    assert env["requests"] == [] and usage_count() == 0
    assert env["c"].get("/api/ai/status").json()["features"]["recipe_url"] is False
    monkeypatch.delenv("ANTHROPIC_API_KEY")  # the switch answers before the missing key
    assert post(env["c"]).status_code == 403


def test_recipe_switch_off_refuses_url_import_too(env):
    with db.conn() as c:
        config.store(c, "ai_allow_recipe", "0")
    r = post(env["c"])
    assert r.status_code == 403 and "recipe import is turned off" in r.json()["detail"]
    assert env["requests"] == []


def test_needs_a_key_and_respects_the_cap(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert post(env["c"]).status_code == 503
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "1")
    assert post(env["c"]).status_code == 200
    r = post(env["c"])
    assert r.status_code == 429 and "Monthly Claude limit" in r.json()["detail"] and len(env["requests"]) == 1


def test_key_resolution_personal_then_shared(env):
    with db.conn() as c:
        config.set_user_secret(c, 2, ai.PERSONAL_KEY, PERSONAL)
    r = post(env["b"])
    assert r.status_code == 200 and r.json()["key_source"] == "personal"
    assert env["headers"][-1]["x-api-key"] == PERSONAL
    r = post(env["c"])
    assert r.status_code == 200 and r.json()["key_source"] == "global"
    assert env["headers"][-1]["x-api-key"] == SECRET
    with db.conn() as c:
        rows = [tuple(x) for x in c.execute("SELECT user_id, key_source FROM ai_usage ORDER BY id")]
    assert rows == [(2, "user"), (1, "global")]


def test_personal_model_keeps_auto_tool_choice(env):
    with db.conn() as c:
        config.set_user_secret(c, 1, ai.PERSONAL_KEY, PERSONAL)
        c.execute("INSERT INTO user_ai(user_id, monthly_cap, model) VALUES (1, 100, 'claude-sonnet-5')")
    assert post(env["c"]).status_code == 200
    assert env["requests"][-1]["model"] == "claude-sonnet-5" and env["requests"][-1]["tool_choice"] == {"type": "auto"}


# ---------- bad input ----------

@pytest.mark.parametrize("body", [
    None, {}, {"url": ""}, {"url": 5}, {"url": "ftp://example.com/r"}, {"url": "javascript:alert(1)"}, {"url": "file:///etc/passwd"},
    {"url": "example.com/recipe"}, {"url": "https://user:pw@example.com/r"}, {"url": "https://user@example.com/r"},
    {"url": "https://example.com/" + "a" * 2000}, {"url": "https://example.com/a b"}, {"url": "https://example.com/\x00"},
    {"url": "https://example.com/\x7f"}, {"url": "https://example.com/<x>"}, {"url": "https://"}, {"url": "https://[::1"},
    {"url": URL, "evil": 1}, {"url": URL, "note": "n" * 301}])
def test_bad_urls_are_refused_before_any_request(env, body):
    r = env["c"].post("/api/recipes/import/url", json=body)
    assert r.status_code == 400, body
    assert env["requests"] == [] and usage_count() == 0


def test_long_but_allowed_url_is_sent(env):
    url = "https://example.com/" + "a" * (2000 - len("https://example.com/"))
    assert post(env["c"], url).status_code == 200


# ---------- fetch trouble, no recipe, size limit ----------

@pytest.mark.parametrize("code,status,words", [
    ("url_not_accessible", 422, "could not read that page"), ("unsupported_content_type", 422, "not a web page or PDF"),
    ("content_too_large", 413, "too large"), ("url_too_long", 422, "250 characters"), ("unavailable", 502, "not available"),
    ("too_many_requests", 502, "busy"), ("max_uses_exceeded", 422, "could not read"), ("something_new", 422, "could not read")])
def test_fetch_errors_name_the_problem_and_suggest_pasting(env, code, status, words):
    env["reply"] = reply(dict(RECIPE, ingredients=[]), error=code)
    r = post(env["c"])
    assert r.status_code == status and words in r.json()["detail"] and "paste the recipe text" in r.json()["detail"].lower()
    assert usage_count() == 1  # Claude answered and used tokens, so the request stays counted


def test_page_without_a_recipe(env):
    env["reply"] = reply(dict(RECIPE, ingredients=[], confidence="This page is a news article."))
    r = post(env["c"])
    assert r.status_code == 422 and r.json()["detail"] == recipe_ai.NO_RECIPE


def test_no_fetch_at_all_is_a_read_failure(env):
    env["reply"] = reply(fetched=False)
    r = post(env["c"])
    assert r.status_code == 422 and "could not read that page" in r.json()["detail"]


def test_no_recipe_tool_is_unreadable(env):
    env["reply"] = reply(data=None)
    r = post(env["c"])
    assert r.status_code == 502 and "paste the recipe text" in r.json()["detail"].lower()


def test_cut_off_page_warns_or_refuses(env, monkeypatch):
    env["reply"] = reply(dict(RECIPE, cut_off=True))
    r = post(env["c"])
    assert r.status_code == 200 and r.json()["warnings"][0] == recipe_ai.CUT_OFF_WARNING
    env["reply"] = reply(dict(RECIPE, cut_off=True, ingredients=[]))
    r = post(env["c"])
    assert r.status_code == 413 and "size limit" in r.json()["detail"]
    monkeypatch.setenv("AI_RECIPE_URL_MAX_CONTENT_TOKENS", "2000")  # page text at the limit (about 4 characters per token)
    env["reply"] = reply(page="x" * 8000)
    r = post(env["c"])
    assert r.status_code == 200 and recipe_ai.CUT_OFF_WARNING in r.json()["warnings"]


def test_upstream_failure_releases_the_reservation(env):
    env["reply"] = httpx.Response(500, json={"error": "x"})
    assert post(env["c"]).status_code == 502
    assert usage_count() == 0


# ---------- cost estimate ----------

def test_status_gives_an_upper_estimate_with_the_page_at_the_limit(env, monkeypatch):
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")
    st = env["c"].get("/api/ai/status", params={"recipe_url": "true"}).json()
    tin, tout = ai.estimate_recipe_url_tokens()
    assert tin >= 30000 and st["est_upper"] is True and st["recipe_url_max_tokens"] == 30000
    assert st["est_cost_label"] == pytest.approx((tin * 1 + tout * 5) / 1e6)
    assert st["action_costs"]["recipe_url"] == pytest.approx(st["est_cost_label"])
    monkeypatch.setenv("AI_RECIPE_URL_MAX_CONTENT_TOKENS", "10000")
    assert env["c"].get("/api/ai/status", params={"recipe_url": "true"}).json()["est_cost_label"] < st["est_cost_label"]
    assert env["c"].get("/api/ai/status").json()["est_upper"] is False


# ---------- source_url on the saved recipe ----------

def import_body(**extra):
    return {"name": "Pancakes", "ingredients": [{"text": "1 cup flour", "amount": 1, "unit": "cup", "name": "flour", "note": None}], **extra}


def test_source_url_is_saved_returned_and_copied(env):
    r = env["c"].post("/api/meals/import", json=import_body(source_url=URL))
    assert r.status_code == 200, r.text
    meal = r.json()
    assert meal["source_url"] == URL
    assert env["c"].get(f"/api/meals/{meal['id']}").json()["source_url"] == URL
    copy = env["c"].post(f"/api/meals/{meal['id']}/duplicate").json()
    assert copy["source_url"] == URL
    plain = env["c"].post("/api/meals/import", json=import_body()).json()
    assert plain["source_url"] is None
    assert env["c"].post("/api/meals/import", json=import_body(source_url="")).json()["source_url"] is None


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "https://u:p@example.com", "ftp://x.org", 5, "https://example.com/" + "a" * 2000])
def test_bad_source_url_is_refused_on_save(env, bad):
    r = env["c"].post("/api/meals/import", json=import_body(source_url=bad))
    assert r.status_code == 400
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 0


def test_migration_adds_the_column_to_an_old_database(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, "
                  "created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO meals(user_id, name) VALUES (1, 'Old')")
    monkeypatch.setenv("DB_PATH", str(path))
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        core.init(c)  # twice is harmless
        cols = {r[1] for r in c.execute("PRAGMA table_info(meals)")}
        assert "source_url" in cols
        assert c.execute("SELECT source_url FROM meals WHERE name='Old'").fetchone()[0] is None
