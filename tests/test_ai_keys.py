import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai, config, db, deps
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GOOD = {"name": "Oats", "brand": None, "serving_text": "40 g", "serving_amount": 40, "serving_unit": "g",
        "serving_g": 40, "serving_ml": None, "kcal": 150, "carbs": 27, "protein": 5, "fat": 3, "fiber": 4,
        "confidence": ""}


def api_reply(tool_input):
    return {"content": [{"type": "tool_use", "id": "t1", "name": ai.TOOL_NAME, "input": tool_input}],
            "stop_reason": "tool_use", "usage": {"input_tokens": 1500, "output_tokens": 120}}

GLOBAL = "sk-ant-global-key-000000000000"
PERSONAL = "sk-ant-personal-key-11111111111"


@pytest.fixture
def env(monkeypatch):
    with db.conn() as c:
        db.init_shared(c)
        ai.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    state = {"user": {"id": 1, "username": "a", "display_name": "A"}, "requests": []}

    def handler(req):
        state["requests"].append(req)
        return httpx.Response(200, json=api_reply(GOOD))

    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(handler))
    api = FastAPI()
    api.include_router(ai.router)
    api.dependency_overrides[deps.current_user] = lambda: state["user"]
    state["client"] = TestClient(api)
    return state


def as_user(env, uid):
    env["user"] = {"id": uid, "username": "u", "display_name": "U"}


def post(env):
    return env["client"].post("/api/ai/label", files=[("images", ("l.jpg", JPEG, "image/jpeg"))])


def set_global(monkeypatch, on=True):
    if on:
        monkeypatch.setenv("ANTHROPIC_API_KEY", GLOBAL)
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def set_personal(uid, key=PERSONAL, cap=None):
    with db.conn() as c:
        config.set_user_secret(c, uid, ai.PERSONAL_KEY, key)
        if cap is not None:
            c.execute("INSERT OR REPLACE INTO user_ai(user_id, monthly_cap) VALUES (?, ?)", (uid, cap))


def use_global(uid, on):
    with db.conn() as c:
        c.execute("UPDATE users SET use_global_ai=? WHERE id=?", (1 if on else 0, uid))


def rows():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT user_id, key_source FROM ai_usage ORDER BY id")]


# ---------------------------------------------------------------- resolution

@pytest.mark.parametrize("personal,allowed,global_set,expected", [
    (True, True, True, "user"), (True, False, True, "user"), (True, True, False, "user"), (True, False, False, "user"),
    (False, True, True, "global"), (False, False, True, None), (False, True, False, None), (False, False, False, None),
])
def test_key_resolution_matrix(env, monkeypatch, personal, allowed, global_set, expected):
    set_global(monkeypatch, global_set)
    use_global(1, allowed)
    if personal:
        set_personal(1)
    source, key = ai.resolve_key(1)
    assert source == expected
    assert key == {"user": PERSONAL, "global": GLOBAL, None: ""}[expected]
    assert ai.enabled(1) is (expected is not None)
    st = env["client"].get("/api/ai/status").json()
    assert st["key_source"] == {"user": "personal", "global": "global", None: None}[expected]
    assert st["enabled"] is (expected is not None)
    assert st["can_use_global"] is (allowed and global_set) and st["personal_key_set"] is personal


def test_no_arg_enabled_reports_household_key(env, monkeypatch):
    set_personal(1)
    assert ai.enabled() is False
    set_global(monkeypatch)
    assert ai.enabled() is True


def test_unknown_user_gets_no_global_key(env, monkeypatch):
    set_global(monkeypatch)
    assert ai.resolve_key(99) == (None, "")


def test_unreadable_personal_key_falls_back(env, monkeypatch):
    set_global(monkeypatch)
    set_personal(1)
    monkeypatch.setenv("SECRET_KEY", "rotated-rotated-rotated-rotated-rotated-1")
    assert ai.resolve_key(1) == ("global", GLOBAL)
    st = env["client"].get("/api/ai/status").json()
    assert st["personal_key_set"] is False and st["personal_key_unreadable"] is True


def test_use_global_off_blocks_global_but_not_personal(env, monkeypatch):
    set_global(monkeypatch)
    use_global(1, False)
    r = post(env)
    assert r.status_code == 503 and "not enabled for your account" in r.json()["detail"]
    assert env["requests"] == []
    set_personal(1)
    r = post(env)
    assert r.status_code == 200 and r.json()["key_source"] == "personal"
    assert env["requests"][0].headers["x-api-key"] == PERSONAL
    assert rows() == [{"user_id": 1, "key_source": "user"}]


def test_global_request_uses_global_key(env, monkeypatch):
    set_global(monkeypatch)
    set_personal(2)
    assert post(env).json()["key_source"] == "global"
    assert env["requests"][0].headers["x-api-key"] == GLOBAL
    as_user(env, 2)
    post(env)
    assert env["requests"][1].headers["x-api-key"] == PERSONAL
    assert rows() == [{"user_id": 1, "key_source": "global"}, {"user_id": 2, "key_source": "user"}]


def test_rejected_personal_key_message(env, monkeypatch):
    set_personal(1)
    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    r = post(env)
    assert r.status_code == 502 and "your personal Claude API key was rejected" in r.json()["detail"]
    assert PERSONAL not in r.text and rows() == []


# ---------------------------------------------------------------- caps

def test_separate_caps_per_source(env, monkeypatch):
    set_global(monkeypatch)
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "1")
    set_personal(2, cap=2)
    assert post(env).status_code == 200  # user 1, global
    r = post(env)
    assert r.status_code == 429 and "ask the administrator" in r.json()["detail"]
    as_user(env, 2)  # personal usage is not limited by the exhausted global cap
    assert post(env).status_code == 200 and post(env).status_code == 200
    r = post(env)
    assert r.status_code == 429 and "your personal key (2" in r.json()["detail"]
    st = env["client"].get("/api/ai/status").json()
    assert (st["key_source"], st["cap"], st["used_this_month"], st["remaining"]) == ("personal", 2, 2, 0)
    assert (st["personal_cap"], st["personal_used_this_month"]) == (2, 2)
    as_user(env, 1)
    st = env["client"].get("/api/ai/status").json()
    assert (st["key_source"], st["cap"], st["used_this_month"], st["personal_used_this_month"]) == ("global", 1, 1, 0)


def test_personal_usage_is_per_user(env, monkeypatch):
    set_personal(1, cap=1)
    set_personal(2, cap=1)
    assert post(env).status_code == 200
    as_user(env, 2)
    assert post(env).status_code == 200
    assert post(env).status_code == 429


def test_cost_per_active_source(env, monkeypatch):
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")
    set_global(monkeypatch)
    post(env)  # global, 1500 in / 120 out
    set_personal(1)
    post(env)
    post(env)  # personal, twice
    st = env["client"].get("/api/ai/status").json()
    assert st["key_source"] == "personal"
    assert st["cost_this_month"] == pytest.approx(2 * (1500 + 120 * 5) / 1e6)
    with db.conn() as c:
        config.delete_user_secret(c, 1, ai.PERSONAL_KEY)
    st = env["client"].get("/api/ai/status").json()
    assert st["key_source"] == "global" and st["cost_this_month"] == pytest.approx((1500 + 600) / 1e6)


def test_concurrent_reservations_per_source_are_atomic(env):
    results = {"global": [], "user1": [], "user2": []}

    def worker(name, uid, source, limit):
        results[name].append(ai.reserve(uid, limit, source))

    threads = []
    for _ in range(8):
        threads.append(threading.Thread(target=worker, args=("global", 1, "global", 3)))
        threads.append(threading.Thread(target=worker, args=("user1", 1, "user", 2)))
        threads.append(threading.Thread(target=worker, args=("user2", 2, "user", 4)))
    [t.start() for t in threads]
    [t.join() for t in threads]
    granted = {k: len([r for r in v if r is not None]) for k, v in results.items()}
    assert granted == {"global": 3, "user1": 2, "user2": 4}
    with db.conn() as c:
        assert ai.used_this_month(c) == 3
        assert ai.used_this_month(c, "user", 1) == 2 and ai.used_this_month(c, "user", 2) == 4


# ---------------------------------------------------------------- key endpoints

def test_put_and_delete_key(env, monkeypatch, caplog):
    caplog.set_level("DEBUG")
    r = env["client"].put("/api/ai/key", json={"key": "  " + PERSONAL + " ", "cap": 25})
    assert r.status_code == 200, r.text
    st = r.json()
    assert (st["personal_key_set"], st["key_source"], st["personal_cap"], st["enabled"]) == (True, "personal", 25, True)
    assert env["requests"] == []  # never calls the API to check the key
    assert ai.resolve_key(1) == ("user", PERSONAL)
    r = env["client"].put("/api/ai/key", json={"cap": 40})  # cap alone keeps the key
    assert r.json()["personal_cap"] == 40 and r.json()["personal_key_set"] is True
    r = env["client"].delete("/api/ai/key")
    assert r.status_code == 200 and r.json()["personal_key_set"] is False and r.json()["enabled"] is False
    assert r.json()["personal_cap"] == 40
    assert PERSONAL not in caplog.text and "saved a personal Claude API key" in caplog.text


@pytest.mark.parametrize("body", [
    {"key": ""}, {"key": "short"}, {"key": "x" * 513}, {"key": "has a space in the middle ok"}, {"key": 12345},
    {"key": PERSONAL + "é"}, {"cap": 0}, {"cap": 10001}, {"cap": 2.5}, {"cap": True}, {"key": PERSONAL, "x": 1},
    {}, None, [PERSONAL],
])
def test_put_key_validation(env, body):
    r = env["client"].put("/api/ai/key", json=body)
    assert r.status_code == 400, (body, r.text)
    assert PERSONAL not in r.text
    with db.conn() as c:
        assert config.user_secret_state(c, 1, ai.PERSONAL_KEY) == "unset"


def test_put_key_without_secret_key_is_503(env, monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    r = env["client"].put("/api/ai/key", json={"key": PERSONAL})
    assert r.status_code == 503 and PERSONAL not in r.text


def test_key_is_per_user(env):
    env["client"].put("/api/ai/key", json={"key": PERSONAL})
    as_user(env, 2)
    assert env["client"].get("/api/ai/status").json()["personal_key_set"] is False
    env["client"].delete("/api/ai/key")
    as_user(env, 1)
    assert env["client"].get("/api/ai/status").json()["personal_key_set"] is True


def test_status_never_contains_keys(env, monkeypatch):
    set_global(monkeypatch)
    set_personal(1)
    text = env["client"].get("/api/ai/status").text + json.dumps(post(env).json())
    assert GLOBAL not in text and PERSONAL not in text
