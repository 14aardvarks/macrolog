"""Personal Claude model and prices, and the administrator's Claude feature switches."""
import json
import sqlite3

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import ai, config, core, db, deps, recipe_ai

GLOBAL = "sk-ant-global-key-000000000000"
PERSONAL = "sk-ant-personal-key-11111111111"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GOOD = {"name": "Oats", "brand": None, "serving_text": "40 g", "serving_amount": 40, "serving_unit": "g",
        "serving_g": 40, "serving_ml": None, "kcal": 150, "carbs": 27, "protein": 5, "fat": 3, "fiber": 4, "confidence": ""}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", GLOBAL)
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        ai.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    st = {"requests": [], "headers": []}

    def handler(req):
        st["requests"].append(json.loads(req.content))
        st["headers"].append(req.headers.get("x-api-key"))
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t", "name": ai.TOOL_NAME, "input": GOOD}],
                                         "usage": {"input_tokens": 1000, "output_tokens": 100}})

    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(handler))
    app = FastAPI()
    for r in (ai.router, core.router, recipe_ai.router):
        app.include_router(r)
    def fake_user(request: Request):
        return {"id": int(request.headers.get("x-user", "1")), "username": "u"}

    app.dependency_overrides[deps.current_user] = fake_user
    st["a"] = TestClient(app)
    st["b"] = TestClient(app, headers={"x-user": "2"})
    return st


def label(client):
    return client.post("/api/ai/label", files=[("images", ("l.jpg", JPEG, "image/jpeg"))])


def personal(uid=1):
    with db.conn() as c:
        config.set_user_secret(c, uid, ai.PERSONAL_KEY, PERSONAL)


# ---------- personal model and prices ----------

def test_personal_fields_default_empty(env):
    st = env["a"].get("/api/ai/status").json()
    assert (st["personal_model"], st["personal_price_in"], st["personal_price_out"]) == ("", None, None)
    assert st["server_model"] == ai.DEFAULT_MODEL and st["personal_cap_default"] == ai.DEFAULT_PERSONAL_CAP == 100


def test_put_personal_model_and_prices_and_clear(env):
    r = env["a"].put("/api/ai/key", json={"model": "  claude-sonnet-x ", "price_in": "3", "price_out": 15.5})
    assert r.status_code == 200, r.text
    st = r.json()
    assert (st["personal_model"], st["personal_price_in"], st["personal_price_out"]) == ("claude-sonnet-x", 3, 15.5)
    assert st["personal_cap"] == 100  # the limit keeps its default
    assert env["b"].get("/api/ai/status").json()["personal_model"] == ""  # per user
    st = env["a"].put("/api/ai/key", json={"model": "", "price_in": None, "price_out": ""}).json()
    assert (st["personal_model"], st["personal_price_in"], st["personal_price_out"]) == ("", None, None)


def test_put_cap_keeps_personal_model(env):
    env["a"].put("/api/ai/key", json={"model": "m1"})
    st = env["a"].put("/api/ai/key", json={"cap": 7}).json()
    assert (st["personal_cap"], st["personal_model"]) == (7, "m1")


@pytest.mark.parametrize("body", [
    {"price_in": -1}, {"price_out": 10001}, {"price_in": "lots"}, {"price_in": True}, {"price_in": [1]},
    {"model": 5}, {"model": "x" * 101}, {"model": "bad\nname"}, {"other": 1}, {},
])
def test_put_personal_validation(env, body):
    assert env["a"].put("/api/ai/key", json=body).status_code == 400
    st = env["a"].get("/api/ai/status").json()
    assert (st["personal_model"], st["personal_price_in"]) == ("", None)


def test_personal_model_and_prices_used_on_own_key(env):
    personal()
    env["a"].put("/api/ai/key", json={"model": "claude-sonnet-x", "price_in": 3, "price_out": 15})
    r = label(env["a"]).json()
    sent = env["requests"][-1]
    assert sent["model"] == "claude-sonnet-x" and sent["tool_choice"] == {"type": "auto"}  # not Haiku, so not forced
    assert env["headers"][-1] == PERSONAL
    assert r["cost"] == pytest.approx((1000 * 3 + 100 * 15) / 1e6)
    st = env["a"].get("/api/ai/status").json()
    assert st["model"] == "claude-sonnet-x" and st["price_known"] is True
    assert st["cost_this_month"] == pytest.approx((1000 * 3 + 100 * 15) / 1e6)


def test_personal_empty_model_uses_server_model_and_no_cost(env):
    personal()
    r = label(env["a"]).json()
    assert env["requests"][-1]["model"] == ai.DEFAULT_MODEL
    assert env["requests"][-1]["tool_choice"] == {"type": "tool", "name": ai.TOOL_NAME}
    assert r["cost"] is None
    st = env["a"].get("/api/ai/status").json()
    assert st["price_known"] is False and st["est_cost_label"] is None


def test_shared_key_users_keep_admin_model_and_prices(env, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "claude-haiku-admin")
    env["b"].put("/api/ai/key", json={"model": "claude-sonnet-x", "price_in": 100, "price_out": 100})  # no personal key
    r = label(env["b"]).json()
    assert env["requests"][-1]["model"] == "claude-haiku-admin" and env["headers"][-1] == GLOBAL
    assert r["cost"] == pytest.approx((1000 + 500) / 1e6)
    st = env["b"].get("/api/ai/status").json()
    assert st["key_source"] == "global" and st["model"] == "claude-haiku-admin" and st["personal_model"] == "claude-sonnet-x"


def test_user_ai_migration_adds_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        c.execute("CREATE TABLE user_ai(user_id INTEGER PRIMARY KEY REFERENCES users(id), monthly_cap INTEGER NOT NULL DEFAULT 100)")
        c.execute("INSERT INTO user_ai VALUES (1, 9)")
        ai.init(c)
        ai.init(c)  # running twice is harmless
        assert ai.personal_settings(c, 1) == {"model": "", "price_in": None, "price_out": None}
        assert ai.personal_cap(c, 1) == 9
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO user_ai(user_id, monthly_cap, model) VALUES (1, 1, '')")


# ---------- feature switches ----------

def turn_off(name):
    with db.conn() as c:
        config.store(c, ai.FEATURES[name][0], "0")


def test_features_default_on_in_status(env):
    assert env["a"].get("/api/ai/status").json()["features"] == {"label": True, "lookup": True, "recipe": True, "recipe_url": False}
    for key in ("ai_allow_label", "ai_allow_lookup", "ai_allow_recipe"):
        assert config.MANAGED[key].kind == "bool" and config.MANAGED[key].default == "1"
    assert config.MANAGED["ai_allow_recipe_url"].kind == "bool" and config.MANAGED["ai_allow_recipe_url"].default == "0"


def test_label_switch_refuses(env):
    turn_off("label")
    r = label(env["a"])
    assert r.status_code == 403 and "label reading is turned off" in r.json()["detail"]
    assert env["requests"] == [] and env["a"].get("/api/ai/status").json()["features"]["label"] is False
    assert env["a"].post("/api/ai/lookup", json={"text": "apple"}).status_code == 200  # other features keep working
    assert core.can_ask_ai(1) is False


def test_lookup_switch_refuses_after_validation(env):
    turn_off("lookup")
    assert env["a"].post("/api/ai/lookup", json={"text": ""}).status_code == 400  # bad input is still a 400
    r = env["a"].post("/api/ai/lookup", json={"text": "apple"})
    assert r.status_code == 403 and "typed search is turned off" in r.json()["detail"]
    assert env["requests"] == [] and label(env["a"]).status_code == 200


def test_recipe_switch_refuses_import_and_match(env):
    turn_off("recipe")
    r = env["a"].post("/api/recipes/import/text", json={"text": "1 cup flour"})
    assert r.status_code == 403 and "recipe import is turned off" in r.json()["detail"]
    assert env["a"].post("/api/recipes/import/photos", files=[("images", ("r.jpg", JPEG, "image/jpeg"))]).status_code == 403
    meal = env["a"].post("/api/meals/import", json={"name": "P", "ingredients": [{"name": "flour"}]}).json()
    r = env["a"].post(f"/api/recipes/{meal['id']}/match", json={"item_ids": [meal["items"][0]["id"]]})
    assert r.status_code == 403
    assert env["requests"] == []
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 0
