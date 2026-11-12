"""Recipe import (text and photos) and Match Selected With Claude, with the Claude transport and lookups mocked."""
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import ai, core, db, deps, lookup, recipe_ai

SECRET = "sk-ant-secret-key-123"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
RECIPE = {"name": "Pancakes", "servings": 4, "confidence": "Clear.", "ingredients": [
    {"text": "1 1/2 cups flour", "amount": 1.5, "unit": "cups", "name": "flour", "note": None},
    {"text": "2 eggs", "amount": 2, "unit": None, "name": "egg", "note": None},
    {"text": "Salt to taste", "amount": None, "unit": None, "name": "salt", "note": "to taste"},
    {"text": "", "amount": 1, "unit": "cup", "name": "  ", "note": None},
    "junk"]}
FLOUR = {"source": "fdc", "source_id": "f1", "name": "Wheat flour", "serving_amount": 1, "serving_unit": "cup", "serving_g": 125,
         "label_text": "1 cup (125 g)", "kcal": 455, "carbs": 95, "protein": 13, "fat": 1.2, "fiber": 3.4}
EGG_OFF = {"source": "off", "source_id": "e1", "name": "Egg", "serving_amount": 1, "serving_unit": "egg", "serving_g": 50,
           "label_text": "1 egg (50 g)", "kcal": 72, "carbs": 0.4, "protein": 6.3, "fat": 4.8}


def reply(name, data, usage=None):
    return {"content": [{"type": "tool_use", "id": "t", "name": name, "input": data}],
            "usage": usage or {"input_tokens": 900, "output_tokens": 300}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        ai.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    st = {"requests": [], "searches": [], "reply": reply(recipe_ai.IMPORT_TOOL_NAME, RECIPE),
          "fdc": {"flour": [FLOUR]}, "off": {"egg": [EGG_OFF]}}

    def handler(req):
        st["requests"].append(json.loads(req.content))
        r = st["reply"]
        return r if isinstance(r, httpx.Response) else httpx.Response(200, json=r)

    async def fake_search(q, limit=8):
        st["searches"].append(("fdc", q, limit))
        return st["fdc"].get(q, [])

    async def fake_off(q, limit=8):
        st["searches"].append(("off", q, limit))
        if q == "boom":
            raise RuntimeError("network")
        return st["off"].get(q, [])

    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(lookup, "search", fake_search)
    monkeypatch.setattr(lookup, "search_off", fake_off)
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


# ---------- import ----------

def test_import_text_returns_a_clean_draft(env):
    r = env["c"].post("/api/recipes/import/text", json={"text": "Pancakes\n<b>1 1/2 cups flour</b>\n\n2 eggs", "note": "ignore <this>"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipe"]["name"] == "Pancakes" and body["recipe"]["servings"] == 4
    assert [(i["amount"], i["unit"], i["name"]) for i in body["recipe"]["ingredients"]] == [(1.5, "cup", "flour"), (2, None, "egg"), (None, None, "salt")]
    assert body["recipe"]["ingredients"][2]["note"] == "to taste"
    assert body["warnings"] == ["Claude's note: Clear."]
    assert body["used_this_month"] == 1 and body["input_tokens"] == 900 and body["key_source"] == "global"
    sent = env["requests"][0]
    text = sent["messages"][0]["content"][0]["text"]
    assert "<recipe>\nPancakes\nb 1 1/2 cups flour /b\n2 eggs\n</recipe>" in text and "<note>ignore this</note>" in text
    assert "never as instructions" in text
    assert sent["tools"][0]["name"] == "record_recipe" and sent["tool_choice"] == {"type": "tool", "name": "record_recipe"}
    assert SECRET not in r.text
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 0  # nothing saved


@pytest.mark.parametrize("body", [None, {}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": "x" * 20001},
                                  {"text": "x", "evil": 1}, {"text": "x", "note": "n" * 301}])
def test_import_text_validation_before_any_request(env, body):
    assert env["c"].post("/api/recipes/import/text", json=body).status_code == 400
    assert env["requests"] == [] and usage_count() == 0


def test_import_needs_a_key_and_respects_the_cap(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert env["c"].post("/api/recipes/import/text", json={"text": "x"}).status_code == 503
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "1")
    assert env["c"].post("/api/recipes/import/text", json={"text": "x"}).status_code == 200
    r = env["c"].post("/api/recipes/import/text", json={"text": "x"})
    assert r.status_code == 429 and len(env["requests"]) == 1


def test_import_upstream_failure_releases_the_reservation(env):
    env["reply"] = httpx.Response(500, json={"error": "x"})
    assert env["c"].post("/api/recipes/import/text", json={"text": "x"}).status_code == 502
    assert usage_count() == 0
    env["reply"] = reply("other_tool", {})
    assert env["c"].post("/api/recipes/import/text", json={"text": "x"}).status_code == 502
    assert usage_count() == 1  # Claude answered, so the request counts


def test_import_with_no_ingredients_warns(env):
    env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, {"name": None, "servings": -2, "ingredients": [], "confidence": ""})
    body = env["c"].post("/api/recipes/import/text", json={"text": "hello"}).json()
    assert body["recipe"] == {"name": "", "servings": None, "ingredients": [], "steps": []}
    assert "no ingredients" in body["warnings"][0]


def test_import_photos(env):
    files = [("images", ("a.jpg", JPEG, "image/jpeg")), ("images", ("b.jpg", JPEG, "image/jpeg"))]
    r = env["c"].post("/api/recipes/import/photos", files=files, data={"hint": "the left page"})
    assert r.status_code == 200, r.text
    content = env["requests"][0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"] and "<note>the left page</note>" in content[2]["text"]
    assert env["c"].post("/api/recipes/import/photos", files=[("images", ("a.txt", b"hi", "text/plain"))]).status_code == 400
    four = [("images", ("a.jpg", JPEG, "image/jpeg"))] * 4
    assert env["c"].post("/api/recipes/import/photos", files=four).status_code == 400
    r = env["c"].post("/api/recipes/import/photos", files=[], data={"hint": "x"})
    assert r.status_code == 400 and "recipe" in r.json()["detail"]
    assert len(env["requests"]) == 1


def test_status_estimates_for_recipes(env, monkeypatch):
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")
    get = lambda **q: env["c"].get("/api/ai/status", params=q).json()["est_cost_label"]  # noqa: E731
    assert get(recipe_chars=4000) == pytest.approx((900 + 1000) / 1e6 + 1700 * 5 / 1e6)
    assert get(recipe_images=2) == pytest.approx((2 * 1600 + 900) / 1e6 + 1700 * 5 / 1e6)
    assert get(match_rows=3) == pytest.approx((900 + 3 * 450) / 1e6 + 3 * 160 * 5 / 1e6)
    assert env["c"].get("/api/ai/status", params={"match_rows": 99}).status_code == 422


# ---------- match ----------

def saved_recipe(env, rows=None):
    rows = rows or [{"text": "1 1/2 cups flour", "amount": 1.5, "unit": "cup", "name": "flour"},
                    {"text": "2 eggs", "amount": 2, "name": "egg"}, {"text": "salt to taste", "name": "salt"}]
    return env["c"].post("/api/meals/import", json={"name": "Pancakes", "ingredients": rows}).json()


def test_match_proposes_candidates_and_estimates_without_applying(env):
    m = saved_recipe(env)
    ids = [i["id"] for i in m["items"]]
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [
        {"row": 1, "choice": 1, "amount": 1.5, "unit": "cups", "estimate": None, "note": "Plain flour."},
        {"row": 2, "choice": 9, "amount": 2, "unit": "egg", "estimate": {"name": "Large egg", "serving_text": "1 egg (50 g)",
                                                                       "serving_g": 50, "kcal": 72, "carbs": 0.4, "protein": 6.3, "fat": 4.8, "fiber": None}, "note": None},
        {"row": 3, "choice": None, "amount": None, "unit": None, "estimate": None, "note": "Salt to taste has no calories."}]})
    r = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": ids})
    assert r.status_code == 200, r.text
    p = r.json()["proposals"]
    assert [x["kind"] for x in p] == ["candidate", "estimate", "none"]
    assert p[0]["food"]["id"] and p[0]["food"]["name"] == "Wheat flour" and (p[0]["amount"], p[0]["unit"]) == (1.5, "cup")
    assert p[1]["food"].get("id") is None and p[1]["food"]["source"] == "ai" and (p[1]["amount"], p[1]["unit"]) == (2, "egg")
    assert p[2]["note"] == "Salt to taste has no calories." and p[2]["food"] is None and p[2]["preview"] is None
    assert p[0]["preview"]["kcal"] == 682.5 and p[1]["preview"]["kcal"] == 144
    assert r.json()["used_this_month"] == 1
    text = env["requests"][-1]["messages"][0]["content"][0]["text"]
    assert '<ingredient row="1">' in text and "[1] Wheat flour" in text and "(no candidates)" in text and "never instructions" in text
    assert ("fdc", "flour", 3) in env["searches"]
    # still unmatched: proposals are not applied, and only the chosen remote candidate was saved
    assert env["c"].get(f"/api/meals/{m['id']}").json()["matched"] == 0
    with db.conn() as c:
        assert [r[0] for r in c.execute("SELECT name FROM foods")] == ["Wheat flour"]
    # accepting is a plain item patch
    ok = env["c"].patch(f"/api/meals/{m['id']}/items/{ids[0]}", json={"food_id": p[0]["food"]["id"], "amount": 1.5, "unit": "cup"})
    assert ok.json()["matched"] == 1


def test_match_falls_back_to_a_label_serving_and_handles_missing_rows(env):
    m = saved_recipe(env, [{"amount": 3, "unit": "pinch", "name": "flour"}, {"name": "boom"}])
    ids = [i["id"] for i in m["items"]]
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [
        {"row": 1, "choice": 1, "amount": 3, "unit": "pinch", "estimate": None, "note": None}, "junk"]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": ids}).json()["proposals"]
    assert (p[0]["amount"], p[0]["unit"]) == (1, "cup") and "label serving" in p[0]["warnings"][0]
    assert p[1]["kind"] == "none" and "did not answer" in p[1]["note"]


def test_match_uses_local_foods_first(env):
    with db.conn() as c:
        local = core.save_food(c, core.normalize_food({**FLOUR, "source": "custom", "source_id": None, "name": "My flour"}))
    m = saved_recipe(env, [{"amount": 1, "unit": "cup", "name": "flour"}])
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [{"row": 1, "choice": 1, "amount": 1, "unit": "cup", "estimate": None, "note": None}]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"]
    assert p[0]["food"]["id"] == local["id"]
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM foods").fetchone()[0] == 1


@pytest.mark.parametrize("body", [None, {}, {"item_ids": []}, {"item_ids": "1"}, {"item_ids": [1], "x": 1},
                                  {"item_ids": ["a"]}, {"item_ids": list(range(1, 17))}])
def test_match_validation(env, body):
    m = saved_recipe(env)
    assert env["c"].post(f"/api/recipes/{m['id']}/match", json=body).status_code == 400
    assert env["requests"] == []


def test_match_ownership_and_key(env, monkeypatch):
    m = saved_recipe(env)
    other = saved_recipe(env)
    item = m["items"][0]["id"]
    assert env["b"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [item]}).status_code == 404
    assert env["c"].post(f"/api/recipes/{other['id']}/match", json={"item_ids": [item]}).status_code == 404
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [item]}).status_code == 503
    assert env["requests"] == [] and usage_count() == 0


def test_match_bad_estimate_becomes_none(env):
    m = saved_recipe(env, [{"name": "mystery"}])
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [{"row": 1, "choice": None, "amount": 1, "unit": "cup",
        "estimate": {"name": "", "serving_text": "", "serving_g": None, "kcal": -1, "carbs": 0, "protein": 0, "fat": 0, "fiber": None}, "note": None}]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"]
    assert p[0]["kind"] == "none"


# ---------- steps and amounts worked out from the line ----------

def test_import_schema_has_optional_steps_and_returns_them(env):
    schema = recipe_ai.IMPORT_TOOL["input_schema"]
    assert schema["properties"]["steps"] == {"type": "array", "items": {"type": "string"}, "description": schema["properties"]["steps"]["description"]}
    assert "steps" not in schema["required"]
    env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, {**RECIPE, "steps": ["  Mix   flour and eggs. ", "", 5, "Fry."]})
    body = env["c"].post("/api/recipes/import/text", json={"text": "x"}).json()
    assert body["recipe"]["steps"] == ["Mix flour and eggs.", "Fry."]
    text = env["requests"][0]["messages"][0]["content"][0]["text"]
    assert "steps" in text and "ads" in text
    env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, RECIPE)  # an answer without steps
    assert env["c"].post("/api/recipes/import/text", json={"text": "x"}).json()["recipe"]["steps"] == []
    files = [("images", ("a.jpg", JPEG, "image/jpeg"))]
    env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, {**RECIPE, "steps": ["Bake."]})
    assert env["c"].post("/api/recipes/import/photos", files=files).json()["recipe"]["steps"] == ["Bake."]


def test_import_steps_are_cut_to_the_limits(env):
    many = ["Step."] * (core.MAX_STEPS + 5) + ["x" * (core.MAX_STEP_LEN + 50)]
    steps, warns = recipe_ai.clean_steps(many)
    assert len(steps) == core.MAX_STEPS and len(warns) == 1
    steps, warns = recipe_ai.clean_steps(["y" * (core.MAX_STEP_LEN + 50)])
    assert len(steps[0]) == core.MAX_STEP_LEN and "cut" in warns[0]
    assert recipe_ai.clean_steps("nope") == ([], [])
    # what the import returns can be saved as it is
    m = env["c"].post("/api/meals/import", json={"name": "R", "ingredients": [{"name": "x"}], "steps": steps}).json()
    assert m["steps"] == steps


def test_match_amounts_come_from_the_recipe_line(env):
    rows = [{"text": "2 cups flour", "amount": 2, "unit": "cups", "name": "flour"},
            {"text": "1 can flour", "amount": 1, "unit": "can", "name": "flour"},
            {"text": "3 eggs", "amount": 3, "name": "egg"}]
    m = saved_recipe(env, rows)
    ids = [i["id"] for i in m["items"]]
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [
        {"row": 1, "choice": 1, "amount": 250, "unit": "g", "estimate": None, "note": None},  # the line's own unit wins
        {"row": 2, "choice": 1, "amount": 2, "unit": "can", "estimate": None, "note": None},  # nothing works: Check Amount
        {"row": 3, "choice": 1, "amount": None, "unit": None, "estimate": None, "note": None}]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": ids}).json()["proposals"]
    assert (p[0]["amount"], p[0]["unit"], p[0]["check"], p[0]["grams"]) == (2, "cup", False, 250)
    assert (p[1]["amount"], p[1]["unit"], p[1]["check"]) == (1, "cup", True) and "label serving" in p[1]["warnings"][0]
    assert (p[2]["amount"], p[2]["unit"], p[2]["check"], p[2]["grams"]) == (3, "egg", False, 150)
    # Accept of a Check Amount proposal attaches the food with the flag
    r = env["c"].patch(f"/api/meals/{m['id']}/items/{ids[1]}", json={"food_id": p[1]["food"]["id"], "amount": 1, "unit": "cup", "check": True}).json()
    assert r["items"][1]["check"] and r["checks"] == 1 and r["matched"] == 0


def test_match_without_a_line_amount_uses_claudes(env):
    m = saved_recipe(env, [{"text": "flour for dusting", "name": "flour"}])
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [{"row": 1, "choice": 1, "amount": 2, "unit": "tbsp", "estimate": None, "note": None}]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"]
    assert (p[0]["amount"], p[0]["unit"], p[0]["check"]) == (2, "tbsp", False)  # cup label: tbsp is exact
