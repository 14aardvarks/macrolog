"""Full Claude Use (issue #26): the per user setting, the cost table, and the automatic Claude steps the server takes part in.
Every automatic step honors the admin switch, a usable key and the monthly cap, and falls back silently without them."""
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import ai, core, db, deps, lookup, recipe_ai

SECRET = "sk-ant-secret-key-123"
SOUP = {"source": "custom", "name": "Lentil Soup", "serving_amount": 1, "serving_unit": "cup", "serving_g": 240,
        "label_text": "1 cup (240 g)", "kcal": 230, "carbs": 40, "protein": 18, "fat": 1}
SPREAD = {"source": "off", "source_id": "3017620422003", "barcode": "3017620422003", "name": "Hazelnut Spread",
          "serving_amount": 15, "serving_unit": "g", "serving_g": 15, "kcal": 80, "carbs": 8, "protein": 1, "fat": 4.5}
MICROS_REPLY = {"fiber": 15.6, "sugars": 2, "saturated_fat": 0.1, "sodium": 480, "cholesterol": 0, "potassium": 730,
                "calcium": 38, "iron": 6.6, "vitamin_d": 0, "confidence": "Typical home made lentil soup."}


def reply(name, data, usage=None):
    return {"content": [{"type": "tool_use", "id": "t", "name": name, "input": data}],
            "usage": usage or {"input_tokens": 560, "output_tokens": 110}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        ai.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    st = {"requests": [], "lookups": [], "reply": reply(ai.MICROS_TOOL_NAME, MICROS_REPLY), "source": None}

    def claude(req):
        st["requests"].append(json.loads(req.content))
        r = st["reply"]
        return r if isinstance(r, httpx.Response) else httpx.Response(200, json=r)

    async def fake_refresh(food):
        st["lookups"].append(food["id"])
        return st["source"] or {"food": None, "note": "Not found in Open Food Facts", "error": None}

    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(claude))
    monkeypatch.setattr(lookup, "refresh", fake_refresh)
    app = FastAPI()
    for r in (ai.router, core.router, recipe_ai.router):
        app.include_router(r)

    def fake_user(request: Request):
        return {"id": int(request.headers.get("x-user", "1")), "username": "u"}

    app.dependency_overrides[deps.current_user] = fake_user
    st["a"] = TestClient(app)
    st["b"] = TestClient(app, headers={"x-user": "2"})
    return st


def saved(data, uid=1):
    with db.conn() as c:
        f = core.save_food(c, core.normalize_food(data, (data["source"],)))
        c.execute("UPDATE foods SET created_by=? WHERE id=?", (uid, f["id"]))
        return f


def full(env, on=True, client="a"):
    r = env[client].put("/api/settings", json={"full_claude": on})
    assert r.status_code == 200 and r.json()["full_claude"] is on


def refresh(env, f, claude=True):
    return env["a"].post(f"/api/foods/{f['id']}/refresh-nutrients", params={"claude": 1} if claude else None)


# ---------- the setting ----------

def test_default_off_per_user_and_validated(env):
    assert env["a"].get("/api/settings").json()["full_claude"] is False
    full(env)
    assert env["a"].get("/api/settings").json()["full_claude"] is True
    assert env["b"].get("/api/settings").json()["full_claude"] is False
    for bad in ("yes", 1, 0, None, "true", [True]):
        assert env["a"].put("/api/settings", json={"full_claude": bad}).status_code == 400
    assert env["a"].get("/api/settings").json()["full_claude"] is True
    # other settings leave it alone, and it leaves them alone
    s = env["a"].put("/api/settings", json={"confirm_ai": False}).json()
    assert s["full_claude"] is True and s["confirm_ai"] is False
    assert env["a"].put("/api/settings", json={"full_claude": False}).json()["confirm_ai"] is False


def test_column_is_added_in_place_off(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.execute("CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT)")
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        c.execute("INSERT INTO settings(user_id) VALUES (1)")
        core.init(c)
        core.init(c)  # safe twice
        assert core.read_settings(c, 1)["full_claude"] is False
        assert "ai_micros" in {r[1] for r in c.execute("PRAGMA table_info(foods)")}


# ---------- cost table ----------

def test_action_costs_from_tokens_with_sample_prices():
    t = ai.action_tokens()
    assert t["label"] == (2300, 400) and t["lookup"] == (700, 400) and t["micros"] == (600, 150)
    assert t["recipe_text"] == (2900, 1700) and t["match"] == (900 + 15 * 450, 15 * 160)
    c = ai.action_costs(None)
    assert c["sample"] is True
    assert c["label"] == pytest.approx((2300 * 0.10 + 400 * 0.50) / 1e6)
    assert c["lookup"] == pytest.approx((700 * 0.10 + 400 * 0.50) / 1e6)
    assert c["micros"] == pytest.approx((600 * 0.10 + 150 * 0.50) / 1e6)
    assert c["heavy_requests"] == 86
    assert c["heavy_month"] == pytest.approx(sum(c[k] * n for k, n in ai.HEAVY_MONTH))
    assert c["heavy_month"] < 0.05  # well under the issue's older figure of about 1 USD


def test_status_uses_set_prices_and_micros_estimate(env, monkeypatch):
    st = env["a"].get("/api/ai/status").json()
    assert st["action_costs"]["sample"] is True and st["est_cost_label"] is None
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")
    st = env["a"].get("/api/ai/status", params={"micros": 3}).json()
    assert st["action_costs"]["sample"] is False
    assert st["action_costs"]["label"] == pytest.approx((2300 + 400 * 5) / 1e6)
    assert st["est_cost_label"] == pytest.approx(3 * (600 + 150 * 5) / 1e6)
    for n in (0, 11):
        assert env["a"].get("/api/ai/status", params={"micros": n}).status_code == 422


# ---------- path 3: Claude fills missing micronutrients on Refresh Nutrients ----------

def test_claude_fills_only_blank_values_and_marks_them(env):
    full(env)
    f = saved({**SOUP, "fiber": 9, "sodium": 1})
    r = refresh(env, f)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["claude_filled"] == ["sugars", "saturated_fat", "cholesterol", "potassium", "calcium", "iron", "vitamin_d"]
    got = body["food"]
    assert got["fiber"] == 9 and got["sodium"] == 1  # never overwritten
    assert got["potassium"] == 730 and got["cholesterol"] == 0
    assert got["ai_micros"] == body["claude_filled"]
    for k in ("name", "kcal", "carbs", "protein", "fat", "serving_g", "source"):
        assert got[k] == f[k]
    assert "Claude estimated" in body["message"]
    assert len(env["requests"]) == 1
    sent = env["requests"][0]
    assert sent["tools"][0]["name"] == ai.MICROS_TOOL_NAME and sent["max_tokens"] == ai.MICROS_MAX_TOKENS
    text = sent["messages"][0]["content"][0]["text"]
    assert "<food>" in text and "Lentil Soup" in text and "fiber" not in text.split("Only these values are wanted:")[1].split(".")[0]
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 1
    # a second refresh has nothing left to fill and sends nothing
    assert refresh(env, f).json()["filled"] == [] and len(env["requests"]) == 1


def test_source_first_then_claude_for_the_rest(env):
    full(env)
    f = saved(SPREAD)
    env["source"] = {"food": {**SPREAD, "sugars": 8.4, "sodium": 5}, "note": "", "error": None}
    body = refresh(env, f).json()
    assert body["food"]["sugars"] == 8.4 and body["food"]["sodium"] == 5  # from the source, not Claude
    assert "sugars" not in body["claude_filled"] and "sodium" not in body["claude_filled"]
    assert set(body["food"]["ai_micros"]) == set(body["claude_filled"])
    assert body["message"].startswith("Filled sugars, sodium. Claude estimated")


def test_out_of_range_and_unasked_values_are_dropped(env):
    full(env)
    env["reply"] = reply(ai.MICROS_TOOL_NAME, {"sodium": 99999, "iron": -1, "calcium": 40, "confidence": "x"})
    f = saved({**SOUP, "fiber": 1, "sugars": 1, "saturated_fat": 1, "cholesterol": 1, "potassium": 1, "vitamin_d": 1})
    body = refresh(env, f).json()
    assert body["claude_filled"] == ["calcium"] and body["food"]["sodium"] is None and body["food"]["iron"] is None


def test_setting_off_ignores_claude_flag(env):
    f = saved(SOUP)
    assert refresh(env, f).status_code == 400  # no source and Claude may not run: as before
    g = saved(SPREAD)
    body = refresh(env, g).json()
    assert "claude_filled" not in body and env["requests"] == []


def test_switch_off_falls_back_silently(env, monkeypatch):
    full(env)
    monkeypatch.setenv("AI_ALLOW_LOOKUP", "0")
    body = refresh(env, saved(SPREAD)).json()
    assert "claude_filled" not in body and env["requests"] == [] and env["lookups"]
    assert refresh(env, saved(SOUP)).status_code == 400


def test_missing_key_falls_back_silently(env, monkeypatch):
    full(env)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    body = refresh(env, saved(SPREAD)).json()
    assert "claude_filled" not in body and "claude_note" not in body and env["requests"] == []


def test_cap_reached_stops_claude_with_one_quiet_note(env, monkeypatch):
    full(env)
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "1")
    first = refresh(env, saved(SOUP)).json()
    assert first["claude_filled"]
    f = saved(SPREAD)
    env["source"] = {"food": {**SPREAD, "sugars": 8.4}, "note": "", "error": None}
    body = refresh(env, f).json()
    assert body["claude_filled"] == [] and body["claude_capped"] is True
    assert body["claude_note"] == core.CLAUDE_CAP_NOTE and body["message"].endswith(core.CLAUDE_CAP_NOTE)
    assert body["filled"] == ["sugars"]  # the source fill still counts
    assert len(env["requests"]) == 1  # nothing was sent past the cap
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 1


def test_claude_failure_keeps_source_fill(env):
    full(env)
    env["reply"] = httpx.Response(500, json={})
    env["source"] = {"food": {**SPREAD, "sugars": 8.4}, "note": "", "error": None}
    body = refresh(env, saved(SPREAD)).json()
    assert body["filled"] == ["sugars"] and body["claude_note"] == core.CLAUDE_FAIL_NOTE
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 0  # released


def test_someone_elses_custom_food_is_still_refused(env):
    full(env)
    f = saved(SOUP, uid=2)
    assert refresh(env, f).status_code == 403 and env["requests"] == []


def test_missing_nutrients_lists_foods_claude_can_fill(env):
    soup, spread = saved(SOUP), saved(SPREAD)
    for f in (soup, spread):
        assert env["a"].post("/api/entries", json={"food_id": f["id"], "amount": 1, "unit": f["serving_unit"]}).status_code == 200
    plain = env["a"].get("/api/foods/missing-nutrients", params={"claude": 1}).json()["ids"]
    assert plain == [spread["id"]]  # setting off: as before
    full(env)
    assert env["a"].get("/api/foods/missing-nutrients").json()["ids"] == [spread["id"]]
    assert env["a"].get("/api/foods/missing-nutrients", params={"claude": 1}).json()["ids"] == [soup["id"], spread["id"]]


def test_editing_a_claude_value_drops_its_mark(env):
    full(env)
    f = saved(SOUP)
    marked = refresh(env, f).json()["food"]["ai_micros"]
    assert "iron" in marked and "sodium" in marked
    r = env["a"].patch(f"/api/foods/{f['id']}", json={"iron": 5})
    assert r.status_code == 200, r.text
    assert "iron" not in r.json()["ai_micros"] and "sodium" in r.json()["ai_micros"]


# ---------- paths 1, 2 and 4 use the existing routes: each refuses past the cap, with the switch off or without a key ----------

ROUTES = [("/api/ai/lookup", {"text": "lentil soup"}, "AI_ALLOW_LOOKUP"),
          ("/api/recipes/import/text", {"text": "1 cup flour"}, "AI_ALLOW_RECIPE")]


@pytest.mark.parametrize("path,body,switch", ROUTES)
def test_automatic_routes_honor_switch_key_and_cap(env, monkeypatch, path, body, switch):
    monkeypatch.setenv(switch, "0")
    assert env["a"].post(path, json=body).status_code == 403
    monkeypatch.delenv(switch)
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "0")
    assert env["a"].post(path, json=body).status_code == 429
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert env["a"].post(path, json=body).status_code == 503
    assert env["requests"] == []


def test_auto_match_claude_route_honors_switch_key_and_cap(env, monkeypatch):
    m = env["a"].post("/api/meals/import", json={"name": "Bread", "ingredients": [{"name": "flour", "amount": 1, "unit": "cup"}]}).json()
    body = {"item_ids": [m["items"][0]["id"]]}
    monkeypatch.setenv("AI_ALLOW_RECIPE", "0")
    assert env["a"].post(f"/api/recipes/{m['id']}/match", json=body).status_code == 403
    monkeypatch.delenv("AI_ALLOW_RECIPE")
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "0")
    assert env["a"].post(f"/api/recipes/{m['id']}/match", json=body).status_code == 429
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert env["a"].post(f"/api/recipes/{m['id']}/match", json=body).status_code == 503
    assert env["requests"] == []


def test_full_claude_survives_other_settings_saves_and_gives_the_client_what_auto_match_reads(env):
    full(env)
    assert env["a"].put("/api/settings", json={"start_screen": "search", "confirm_ai": False}).json()["full_claude"] is True
    assert env["a"].put("/api/settings/display", json={"auto_match": "search"}).status_code == 200
    assert env["a"].get("/api/settings").json()["full_claude"] is True  # a stored explicit Search is the default, not a choice
    assert env["a"].get("/api/settings/display").json()["auto_match"] == "search"
    st = env["a"].get("/api/ai/status").json()  # the client plan reads exactly these
    assert st["enabled"] is True and st["features"]["recipe"] is True and st["remaining"] > 0
    assert env["b"].get("/api/settings").json()["full_claude"] is False
