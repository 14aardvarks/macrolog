import sys
import types
from datetime import date, timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import app as app_pkg
from app import core, db, deps, lookup

TODAY = date.today().isoformat()
BREAD = {"name": "Bread", "brand": "Bakery", "serving_amount": 1, "serving_unit": "slice", "serving_g": 34,
         "label_text": "1 slice (34 g)", "kcal": 90, "carbs": 17, "protein": 4, "fat": 1.5, "fiber": 3}
PB = {"name": "Peanut Butter", "serving_amount": 2, "serving_unit": "Tbsp.", "serving_g": 32, "serving_ml": 30,
      "label_text": "2 tbsp (32 g)", "kcal": 190, "carbs": 7, "protein": 8, "fat": 16, "fiber": 2}
SALT = {"name": "Mystery", "serving_amount": 100, "serving_unit": "g", "kcal": 100, "carbs": 10, "protein": 10, "fat": 1}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    calls = {"barcode": [], "search": [], "search_off": []}

    async def fake_barcode(raw):
        calls["barcode"].append(raw)
        return calls.get("barcode_result") or {"food": None, "note": "Not found", "valid": True}

    async def fake_search(query, limit=8, state=None):
        calls["search"].append(query)
        return calls.get("search_result", [])

    monkeypatch.setattr(lookup, "barcode", fake_barcode)
    async def fake_search_off(query, limit=8):
        calls["search_off"].append(query)
        return calls.get("off_result", [])

    monkeypatch.setattr(lookup, "search", fake_search)
    monkeypatch.setattr(lookup, "search_off", fake_search_off)
    api = FastAPI()
    api.include_router(core.router)

    def fake_user(request: Request):
        return {"id": int(request.headers["x-user"]), "username": "u", "display_name": "U"}

    api.dependency_overrides[deps.current_user] = fake_user
    calls["a"] = TestClient(api, headers={"x-user": "1"})
    calls["b"] = TestClient(api, headers={"x-user": "2"})
    return calls


@pytest.fixture
def a(env):
    return env["a"]


@pytest.fixture
def b(env):
    return env["b"]


def food(client, data=BREAD):
    r = client.post("/api/foods", json=data)
    assert r.status_code == 200, r.text
    return r.json()


def log(client, f, amount=1, unit=None, **kw):
    body = {"food_id": f["id"], "amount": amount, "unit": unit or f["serving_unit"], **kw}
    r = client.post("/api/entries", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def off_food(**kw):
    return {"source": "fdc", "source_id": "111", "barcode": "073472001011", "name": "Remote Rice", "brand": None,
            "serving_amount": 1, "serving_unit": "cup", "serving_g": 160, "serving_ml": None,
            "label_text": "1 cup", "kcal": 200, "carbs": 44, "protein": 4, "fat": 0.4, "fiber": 0.6} | kw


# ---------- foods ----------

def test_create_food_parses_unit_and_reports_units(a):
    f = food(a, PB)
    assert f["serving_unit"] == "tbsp" and f["source"] == "custom" and f["id"]
    got = a.get(f"/api/foods/{f['id']}").json()
    assert got["units"][0]["unit"] == "tbsp" and got["units"][0]["default_amount"] == 2
    assert got["favorite"] is False and got["last"] is None
    assert a.get("/api/foods/999").status_code == 404


@pytest.mark.parametrize("patch", [{"kcal": -1}, {"name": " "}, {"serving_amount": 0}, {"source": "off"},
                                   {"kcal": None}, {"carbs": "x"}, {"serving_unit": ""}, {"fiber": -2}])
def test_create_food_validation(a, patch):
    assert a.post("/api/foods", json=BREAD | patch).status_code == 400


def test_create_food_normalizes_barcode_and_accepts_ai_source(a):
    f = food(a, BREAD | {"barcode": "0 73472 00101 1", "source": "ai"})
    assert f["source"] == "ai" and f["barcode"] == "073472001011"
    assert a.post("/api/foods", json=BREAD | {"serving_unit": "slice", "serving_g": None}).status_code == 200


def test_unit_must_be_available(a):
    f = food(a, BREAD | {"serving_g": None, "name": "Slice only"})
    assert [u["unit"] for u in a.get(f"/api/foods/{f['id']}").json()["units"]] == ["slice", "serving", "pct", "count"]
    r = a.post("/api/entries", json={"food_id": f["id"], "amount": 10, "unit": "g"})
    assert r.status_code == 400 and "not available" in r.json()["detail"]
    assert a.get("/api/preview", params={"food_id": f["id"], "amount": 10, "unit": "g"}).status_code == 400


def test_preview_passes_estimated_through_and_rounds(a):
    f = food(a, PB | {"serving_ml": None, "serving_g": None})
    p = a.get("/api/preview", params={"food_id": f["id"], "amount": 30, "unit": "g"}).json()
    assert p["estimated"] is True
    exact = a.get("/api/preview", params={"food_id": f["id"], "amount": 1, "unit": "tbsp"}).json()
    assert exact["estimated"] is False and exact["kcal"] == 95 and exact["servings"] == 0.5
    third = food(a, SALT)
    p = a.get("/api/preview", params={"food_id": third["id"], "amount": 33, "unit": "g"}).json()
    assert p["kcal"] == 33 and p["carbs"] == 3.3
    p = a.get("/api/preview", params={"food_id": food(a, BREAD)["id"], "amount": 7, "unit": "g"}).json()
    assert p["kcal"] == round(90 * 7 / 34, 2) and p["fiber"] == round(3 * 7 / 34, 2)
    for bad_amount in ("0", "-1", "abc", "inf", "nan", ""):
        r = a.get("/api/preview", params={"food_id": f["id"], "amount": bad_amount, "unit": "g"})
        assert r.status_code == 400, bad_amount


# ---------- barcode ----------

def fake_ai(monkeypatch, enabled, label=True):
    mod = types.ModuleType("app.ai")
    mod.enabled = lambda user_id=None: enabled
    mod.feature_on = lambda name: label
    monkeypatch.setitem(sys.modules, "app.ai", mod)
    monkeypatch.setattr(app_pkg, "ai", mod, raising=False)


def test_barcode_found_is_saved_then_served_locally(env, a, b):
    env["barcode_result"] = {"food": off_food(), "note": "", "valid": True}
    r = a.get("/api/foods/barcode/073472001011").json()
    assert r["food"]["id"] and r["food"]["name"] == "Remote Rice" and r["valid"] is True
    assert len(env["barcode"]) == 1
    # Same product by another spelling (13 digit) and by the other user: local, no network.
    for client, code in ((a, "0073472001011"), (b, "073472001011")):
        again = client.get(f"/api/foods/barcode/{code}").json()
        assert again["food"]["id"] == r["food"]["id"]
    assert len(env["barcode"]) == 1


def test_barcode_matches_custom_food_by_any_candidate(env, a):
    f = food(a, BREAD | {"barcode": "073472001011"})
    assert a.get("/api/foods/barcode/0073472001011").json()["food"]["id"] == f["id"]
    assert env["barcode"] == []


def test_barcode_prefers_user_entered_food_over_older_remote(env, a):
    with db.conn() as c:
        c.execute("INSERT INTO foods(source, source_id, barcode, name, serving_amount, serving_unit, kcal, carbs,"
                  " protein, fat) VALUES ('off','1','073472001011','Remote',1,'g',1,1,1,1)")
    mine = food(a, BREAD | {"barcode": "073472001011"})
    newer_ai = food(a, BREAD | {"barcode": "073472001011", "name": "Scanned", "source": "ai"})
    got = a.get("/api/foods/barcode/073472001011").json()["food"]
    assert got["id"] == newer_ai["id"] and got["id"] > mine["id"]  # custom/ai first, newest first
    with db.conn() as c:
        c.execute("DELETE FROM foods WHERE id=?", (newer_ai["id"],))
    assert a.get("/api/foods/barcode/073472001011").json()["food"]["id"] == mine["id"]


def test_barcode_upce_finds_food_saved_under_upca(env, a):
    f = food(a, BREAD | {"barcode": "012345000065"})
    assert a.get("/api/foods/barcode/01234565").json()["food"]["id"] == f["id"]
    assert env["barcode"] == []


def test_barcode_not_found_and_can_ask_ai(env, a, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.ai", None)  # import fails
    monkeypatch.delattr(app_pkg, "ai", raising=False)
    r = a.get("/api/foods/barcode/4006381333931").json()
    assert r["food"] is None and r["note"] == "Not found" and r["can_ask_ai"] is False
    fake_ai(monkeypatch, True)
    assert a.get("/api/foods/barcode/4006381333931").json()["can_ask_ai"] is True
    fake_ai(monkeypatch, True, label=False)  # the administrator turned label reading off
    assert a.get("/api/foods/barcode/4006381333931").json()["can_ask_ai"] is False
    fake_ai(monkeypatch, False)
    assert a.get("/api/foods/barcode/4006381333931").json()["can_ask_ai"] is False


def test_barcode_with_unusable_remote_food(env, a):
    env["barcode_result"] = {"food": off_food(kcal=-5), "note": "", "valid": True}
    r = a.get("/api/foods/barcode/073472001011").json()
    assert r["food"] is None and "unusable" in r["note"]


# ---------- search ----------

def test_search_order_saves_remote_and_dedupes(env, a, b):
    rice = food(a, BREAD | {"name": "Rice Cake"})
    plain = food(a, BREAD | {"name": "Brown RICE", "brand": None})
    fav = food(a, BREAD | {"name": "Zebra rice"})
    a.post(f"/api/favorites/{fav['id']}")
    env["search_result"] = [off_food(), off_food(source_id="222", name="Other Rice")]
    ids = [f["name"] for f in a.get("/api/foods/search", params={"q": "rice"}).json()["results"]]
    assert ids[0] == "Zebra rice"
    assert ids[1:3] == ["Rice Cake", "Brown RICE"] and ids[3:] == ["Remote Rice", "Other Rice"]
    assert rice["id"] and plain["id"]
    # Second search: remote foods are now local and not duplicated.
    again = a.get("/api/foods/search", params={"q": "rice"}).json()["results"]
    assert len(again) == 5 and all(f["id"] for f in again)
    with db.conn() as c:
        assert c.execute("SELECT count(*) FROM foods WHERE source='fdc'").fetchone()[0] == 2
    # The other user has no favorites, so the order differs but foods are shared.
    other = [f["name"] for f in b.get("/api/foods/search", params={"q": "rice"}).json()["results"]]
    assert "Zebra rice" in other and other[0] != "Zebra rice"


def test_search_matches_brand_words_and_escapes_wildcards(env, a):
    food(a, BREAD | {"name": "Loaf", "brand": "Sunny Bakery"})
    food(a, BREAD | {"name": "100% Juice", "brand": None})
    names = lambda q: [f["name"] for f in a.get("/api/foods/search", params={"q": q}).json()["results"]]
    assert names("bakery sunny") == ["Loaf"]
    assert names("100%") == ["100% Juice"]
    assert names("%") == ["100% Juice"] and names("_") == []
    assert a.get("/api/foods/search", params={"q": " "}).json() == {"results": []}


def test_search_remote_zero_skips_usda(env, a):
    local = food(a, BREAD | {"name": "Rice Cake"})
    env["search_result"] = [off_food()]
    r = a.get("/api/foods/search", params={"q": "rice", "remote": 0}).json()["results"]
    assert [f["id"] for f in r] == [local["id"]] and env["search"] == []
    with db.conn() as c:
        assert c.execute("SELECT count(*) FROM foods WHERE source='fdc'").fetchone()[0] == 0


def test_search_remote_defaults_to_on_and_remote_one(env, a):
    env["search_result"] = [off_food()]
    for params in ({"q": "rice"}, {"q": "rice", "remote": 1}):
        names = [f["name"] for f in a.get("/api/foods/search", params=params).json()["results"]]
        assert names == ["Remote Rice"]
    assert env["search"] == ["rice", "rice"]


def test_search_remote_zero_keeps_favorites(env, a):
    fav = food(a, BREAD | {"name": "Zebra rice"})
    a.post(f"/api/favorites/{fav['id']}")
    r = a.get("/api/foods/search", params={"q": "rice", "remote": 0}).json()["results"]
    assert [f["id"] for f in r] == [fav["id"]]


def test_search_skips_bad_remote_food(env, a):
    env["search_result"] = [off_food(kcal=-1), off_food(source_id="9")]
    assert [f["source_id"] for f in a.get("/api/foods/search", params={"q": "x"}).json()["results"]] == ["9"]


def test_search_all_sources_queries_usda_then_open_food_facts(env, a):
    env["search_result"] = [off_food()]
    env["off_result"] = [off_food(source="off", source_id="5000159407236", name="Rice Pudding")]
    r = a.get("/api/foods/search", params={"q": "rice", "source": "all"}).json()["results"]
    assert [(f["source"], f["name"]) for f in r] == [("fdc", "Remote Rice"), ("off", "Rice Pudding")]
    assert env["search"] == ["rice"] and env["search_off"] == ["rice"]


def test_search_one_source_only(env, a):
    custom = food(a, BREAD | {"name": "Rice Cake"})
    env["search_result"] = [off_food()]
    env["off_result"] = [off_food(source="off", source_id="5000159407236", name="Rice Pudding")]
    off = a.get("/api/foods/search", params={"q": "rice", "source": "off"}).json()["results"]
    assert [f["name"] for f in off] == ["Rice Pudding"] and env["search"] == []
    fdc = a.get("/api/foods/search", params={"q": "rice", "source": "fdc"}).json()["results"]
    assert [f["name"] for f in fdc] == ["Remote Rice"] and env["search_off"] == ["rice"]
    # Local matches follow the source too, so a custom food shows only under All.
    typing = a.get("/api/foods/search", params={"q": "rice", "source": "off", "remote": 0}).json()["results"]
    assert [f["name"] for f in typing] == ["Rice Pudding"]
    every = [f["id"] for f in a.get("/api/foods/search", params={"q": "rice", "remote": 0}).json()["results"]]
    assert custom["id"] in every


def test_search_bad_source_400(env, a):
    assert a.get("/api/foods/search", params={"q": "rice", "source": "ai"}).status_code == 400


# ---------- id parsing ----------

@pytest.mark.parametrize("bad", ["\u00b2", "\u0663", "\uff11", "1\u00b2", "-1", "1.5", " 1", ""])
def test_non_ascii_digit_ids_are_rejected_not_500(a, bad):
    f = food(a, BREAD)
    r = a.post("/api/entries", json={"food_id": bad, "amount": 1, "unit": "slice"})
    assert r.status_code == 400 and "food_id" in r.json()["detail"]
    r = a.post("/api/meals", json={"name": "M", "items": [{"food_id": bad, "amount": 1, "unit": "slice"}]})
    assert r.status_code == 400 and "food_id" in r.json()["detail"]
    ok = a.post("/api/entries", json={"food_id": str(f["id"]), "amount": 1, "unit": "slice"})
    assert ok.status_code == 200  # plain ASCII digit strings still work


# ---------- entries and the day ----------

def test_entry_snapshot_survives_food_change_and_rounds(a):
    f = food(a, BREAD)
    e = log(a, f, 3, "g", day="2025-03-01", meal="lunch")
    assert e["kcal"] == round(90 * 3 / 34, 2) and e["amount"] == 3 and e["unit"] == "g" and e["name"] == "Bread"
    with db.conn() as c:
        c.execute("UPDATE foods SET name='Changed', kcal=9999 WHERE id=?", (f["id"],))
    day = a.get("/api/day", params={"day": "2025-03-01"}).json()
    assert day["entries"][0]["name"] == "Bread" and day["entries"][0]["kcal"] == e["kcal"]


def test_day_entries_carry_the_food_source(a):
    custom = food(a, BREAD)
    ai = food(a, {**BREAD, "name": "Photo Bar", "source": "ai"})
    log(a, custom, 1, day="2025-03-01")
    log(a, ai, 1, day="2025-03-01")
    gone = log(a, custom, 2, day="2025-03-01")
    with db.conn() as c:
        c.execute("UPDATE entries SET food_id=NULL WHERE id=?", (gone["id"],))
    got = a.get("/api/day", params={"day": "2025-03-01"}).json()["entries"]
    assert [e["source"] for e in got] == ["custom", "ai", None]
    assert "source" not in gone


def test_day_totals_targets_percent_remaining(a):
    f = food(a, BREAD)
    log(a, f, 2, day="2025-03-01")
    log(a, f, 1, day="2025-03-01")
    log(a, f, 1, day="2025-03-02")
    d = a.get("/api/day", params={"day": "2025-03-01"}).json()
    assert d["day"] == "2025-03-01" and len(d["entries"]) == 2
    assert d["totals"] == {"kcal": 270, "carbs": 51, "protein": 12, "fat": 4.5, "fiber": 9}
    assert d["targets"] == {"kcal": 3000, "carbs": 375, "protein": 225, "fat": 66.7}
    assert d["percent"] == {"kcal": 9, "carbs": 14, "protein": 5, "fat": 7}
    assert d["remaining"] == {"kcal": 2730, "carbs": 324, "protein": 213, "fat": 62.2}
    assert all(isinstance(v, int) for v in d["percent"].values())


def test_day_defaults_to_server_today_and_validates(a):
    assert a.get("/api/day").json()["day"] == TODAY
    log(a, food(a, BREAD))
    assert len(a.get("/api/day").json()["entries"]) == 1
    assert a.get("/api/day", params={"day": "2025-13-40"}).status_code == 400
    assert a.get("/api/day", params={"day": "yesterday"}).status_code == 400


def test_day_over_goal_has_negative_remaining(a):
    a.put("/api/goals", json={"kcal": 100, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20})
    log(a, food(a, BREAD), 2)
    d = a.get("/api/day").json()
    assert d["percent"]["kcal"] == 180 and d["remaining"]["kcal"] == -80


@pytest.mark.parametrize("body", [{"amount": 0}, {"amount": -2}, {"amount": "abc"}, {"amount": None}, {"unit": "x" * 31},
                                  {"unit": "y" * 40}, {"meal": "brunch"}, {"day": "2025/01/01"}, {"food_id": "x"},
                                  {"food_id": True}])
def test_entry_validation(a, body):
    f = food(a, BREAD)
    good = {"food_id": f["id"], "amount": 1, "unit": "slice"}
    assert a.post("/api/entries", json=good | body).status_code == 400


def test_entry_rejects_non_finite_and_missing_food(a):
    f = food(a, BREAD)
    for raw in ('{"food_id": %d, "amount": NaN, "unit": "slice"}', '{"food_id": %d, "amount": Infinity, "unit": "slice"}'):
        r = a.post("/api/entries", content=raw % f["id"], headers={"content-type": "application/json"})
        assert r.status_code == 400
    assert a.post("/api/entries", json={"food_id": 999, "amount": 1, "unit": "slice"}).status_code == 404


def test_patch_and_delete_entry(a):
    f = food(a, BREAD)
    e = log(a, f, 1, meal="snack", day="2025-03-01")
    r = a.patch(f"/api/entries/{e['id']}", json={"amount": 2, "meal": None}).json()
    assert r["amount"] == 2 and r["meal"] is None and r["kcal"] == 180 and r["servings"] == 2
    r = a.patch(f"/api/entries/{e['id']}", json={"unit": "g", "amount": 34}).json()
    assert r["unit"] == "g" and r["kcal"] == 90
    assert a.patch(f"/api/entries/{e['id']}", json={"unit": "x" * 31}).status_code == 400
    assert a.patch(f"/api/entries/{e['id']}", json={"meal": "x"}).status_code == 400
    assert a.patch(f"/api/entries/{e['id']}", json={}).status_code == 400
    assert a.delete(f"/api/entries/{e['id']}").status_code == 200
    assert a.delete(f"/api/entries/{e['id']}").status_code == 404


def test_entries_isolated_between_users(a, b):
    f = food(a, BREAD)
    e = log(a, f, day="2025-03-01")
    assert b.get("/api/day", params={"day": "2025-03-01"}).json()["entries"] == []
    assert b.patch(f"/api/entries/{e['id']}", json={"amount": 5}).status_code == 404
    assert b.delete(f"/api/entries/{e['id']}").status_code == 404
    assert a.get("/api/day", params={"day": "2025-03-01"}).json()["entries"][0]["amount"] == 1
    assert b.get(f"/api/foods/{f['id']}").json()["last"] is None  # foods shared, last_used not
    assert a.get(f"/api/foods/{f['id']}").json()["last"] == {"amount": 1, "unit": "slice"}


# ---------- quick lists and favorites ----------

def test_quick_yesterday_distinct_foods_with_last_amount(a, b):
    bread, pb = food(a, BREAD), food(a, PB)
    log(a, bread, 1, day="2025-03-01")
    log(a, pb, 2, "tbsp", day="2025-03-01")
    log(a, bread, 68, "g", day="2025-03-01")
    log(a, pb, 1, "tbsp", day="2025-02-27")  # not the previous day
    log(b, bread, 5, day="2025-03-01")
    items = a.get("/api/quick/yesterday", params={"day": "2025-03-02"}).json()["items"]
    assert [(i["food"]["name"], i["amount"], i["unit"]) for i in items] == [("Peanut Butter", 2, "tbsp"), ("Bread", 68, "g")]
    assert items[1]["servings"] == 2 and items[1]["kcal"] == 180 and items[1]["protein"] == 8
    assert items[0]["food"]["id"] == pb["id"]
    assert a.get("/api/quick/yesterday", params={"day": "2025-03-05"}).json() == {"items": []}
    assert len(b.get("/api/quick/yesterday", params={"day": "2025-03-02"}).json()["items"]) == 1


def test_quick_yesterday_defaults_relative_to_today(a):
    log(a, food(a, BREAD), day=(date.today() - timedelta(days=1)).isoformat())
    assert len(a.get("/api/quick/yesterday").json()["items"]) == 1


def test_quick_recent_limit_and_order(a, b):
    foods = [food(a, BREAD | {"name": f"F{i}"}) for i in range(22)]
    for f in foods:
        log(a, f)
    log(a, foods[0], 3)  # most recent now
    items = a.get("/api/quick/recent").json()["items"]
    assert len(items) == 20 and items[0]["food"]["name"] == "F0" and items[0]["amount"] == 3
    assert items[1]["food"]["name"] == "F21" and "F1" not in [i["food"]["name"] for i in items]
    assert b.get("/api/quick/recent").json() == {"items": []}


def test_favorites_quick_default_amount_and_isolation(a, b):
    f, g = food(a, PB), food(a, BREAD)
    assert a.post(f"/api/favorites/{f['id']}").status_code == 200
    assert a.post(f"/api/favorites/{f['id']}").status_code == 200  # idempotent
    a.post(f"/api/favorites/{g['id']}")
    log(a, g, 2, "slice")
    items = a.get("/api/quick/favorites").json()["items"]
    assert [(i["food"]["name"], i["amount"], i["unit"]) for i in items] == [("Bread", 2, "slice"), ("Peanut Butter", 2, "tbsp")]
    assert a.get(f"/api/foods/{f['id']}").json()["favorite"] is True
    assert b.get(f"/api/foods/{f['id']}").json()["favorite"] is False
    assert b.get("/api/quick/favorites").json() == {"items": []}
    assert a.post("/api/favorites/999").status_code == 404
    a.delete(f"/api/favorites/{f['id']}")
    assert len(a.get("/api/quick/favorites").json()["items"]) == 1


# ---------- meals ----------

def test_meal_log_items_accept_any_supported_unit(a):
    pb = food(a, PB)
    m = a.post("/api/meals", json={"name": "PB", "items": [{"food_id": pb["id"], "amount": 2, "unit": "tbsp"}]}).json()
    supported = [u["unit"] for u in a.get(f"/api/foods/{pb['id']}").json()["units"]]
    assert {"g", "oz", "cup", "ml"} <= set(supported)
    for unit, amount in (("g", 16), ("cup", 0.25), ("oz", 1)):
        e = a.post(f"/api/meals/{m['id']}/log", json={"items": [{"food_id": pb["id"], "amount": amount, "unit": unit}]}).json()["entries"][0]
        assert (e["unit"], e["amount"]) == (unit, amount) and e["kcal"] > 0
    assert a.post(f"/api/meals/{m['id']}/log", json={"items": [{"food_id": pb["id"], "amount": 1, "unit": "slice"}]}).status_code == 200  # a typed unit counts like count
    assert a.get("/api/meals").json()["meals"][0]["items"][0]["unit"] == "tbsp"  # the saved recipe is untouched


def test_meal_create_list_log_delete(a, b):
    bread, pb = food(a, BREAD), food(a, PB)
    items = [{"food_id": bread["id"], "amount": 2, "unit": "slice"}, {"food_id": pb["id"], "amount": 1, "unit": "tbsp"}]
    m = a.post("/api/meals", json={"name": "Toast", "items": items}).json()
    assert m["name"] == "Toast" and [i["amount"] for i in m["items"]] == [2, 1] and m["kcal"] == 275
    assert a.get("/api/meals").json()["meals"][0]["id"] == m["id"] and b.get("/api/meals").json() == {"meals": []}
    assert b.post(f"/api/meals/{m['id']}/log", json={}).status_code == 404
    assert b.delete(f"/api/meals/{m['id']}").status_code == 404
    entries = a.post(f"/api/meals/{m['id']}/log", json={"day": "2025-03-01", "meal": "breakfast"}).json()["entries"]
    assert [(e["name"], e["meal"], e["day"]) for e in entries] == [("Bread", "breakfast", "2025-03-01"),
                                                                     ("Peanut Butter", "breakfast", "2025-03-01")]
    over = [{"food_id": pb["id"], "amount": 4, "unit": "tbsp"}]
    e2 = a.post(f"/api/meals/{m['id']}/log", json={"items": over}).json()["entries"]
    assert len(e2) == 1 and e2[0]["amount"] == 4 and e2[0]["day"] == TODAY and e2[0]["meal"] is None
    assert a.post(f"/api/meals/{m['id']}/log").status_code == 200  # no body at all
    last = a.get(f"/api/foods/{pb['id']}").json()["last"]
    assert last == {"amount": 1, "unit": "tbsp"}
    assert a.delete(f"/api/meals/{m['id']}").status_code == 200
    assert a.get("/api/meals").json() == {"meals": []}
    assert a.delete(f"/api/meals/{m['id']}").status_code == 404


def test_meal_log_updates_last_used_for_that_user_only(a, b):
    f = food(a, BREAD)
    m = a.post("/api/meals", json={"name": "M", "items": [{"food_id": f["id"], "amount": 3, "unit": "slice"}]}).json()
    a.post(f"/api/meals/{m['id']}/log", json={})
    assert a.get("/api/quick/recent").json()["items"][0]["amount"] == 3
    assert b.get("/api/quick/recent").json() == {"items": []}


def test_meal_validation(a):
    f = food(a, BREAD)
    ok = {"food_id": f["id"], "amount": 1, "unit": "slice"}
    assert a.post("/api/meals", json={"name": "", "items": [ok]}).status_code == 400
    assert a.post("/api/meals", json={"name": "x", "items": []}).status_code == 400
    assert a.post("/api/meals", json={"name": "x", "items": [ok | {"amount": 0}]}).status_code == 400
    assert a.post("/api/meals", json={"name": "x", "items": [ok | {"unit": "x" * 31}]}).status_code == 400
    assert a.post("/api/meals", json={"name": "x", "items": [ok | {"food_id": 99}]}).status_code == 404
    assert a.post("/api/meals", json={"name": "x", "items": ["nope"]}).status_code == 400
    m = a.post("/api/meals", json={"name": "x", "items": [ok]}).json()
    assert a.post(f"/api/meals/{m['id']}/log", json={"meal": "brunch"}).status_code == 400
    assert a.post(f"/api/meals/{m['id']}/log", json={"items": []}).status_code == 400
    assert a.get("/api/day").json()["entries"] == []  # nothing half logged


def test_meal_from_day_copies_amounts(a, b):
    bread, pb = food(a, BREAD), food(a, PB)
    e1 = log(a, bread, 68, "g", day="2025-03-01")
    e2 = log(a, pb, 3, "tbsp", day="2025-03-01")
    log(a, bread, 1, day="2025-03-02")
    m = a.post("/api/meals/from-day", json={"name": "Day", "day": "2025-03-01"}).json()
    assert [(i["food"]["name"], i["amount"], i["unit"]) for i in m["items"]] == [("Bread", 68, "g"), ("Peanut Butter", 3, "tbsp")]
    m2 = a.post("/api/meals/from-day", json={"name": "Part", "day": "2025-03-01", "entry_ids": [e2["id"]]}).json()
    assert len(m2["items"]) == 1 and m2["items"][0]["food_id"] == pb["id"]
    assert a.post("/api/meals/from-day", json={"name": "x", "day": "2025-03-01", "entry_ids": [999]}).status_code == 400
    assert a.post("/api/meals/from-day", json={"name": "x", "day": "2025-03-09"}).status_code == 400
    # Another user cannot copy my entries.
    assert b.post("/api/meals/from-day", json={"name": "x", "day": "2025-03-01"}).status_code == 400
    assert b.post("/api/meals/from-day", json={"name": "x", "day": "2025-03-01", "entry_ids": [e1["id"]]}).status_code == 400


# ---------- meal field on quick lists, recipe meals ----------

def test_quick_lists_carry_the_most_recent_meal_of_each_food(a, b):
    bread, pb, salt = food(a, BREAD), food(a, PB), food(a, SALT)
    for f in (bread, pb, salt):
        a.post(f"/api/favorites/{f['id']}")
    log(a, bread, meal="breakfast")
    log(a, bread, meal="dinner")
    log(a, pb, 2, "tbsp", meal="snack")
    log(a, pb, 1, "tbsp")  # most recent entry has no meal
    log(b, salt, 100, meal="lunch")  # another user's entry must not leak
    fav = {i["food"]["name"]: i["meal"] for i in a.get("/api/quick/favorites").json()["items"]}
    assert fav == {"Bread": "dinner", "Peanut Butter": None, "Mystery": None}
    rec = {i["food"]["name"]: i["meal"] for i in a.get("/api/quick/recent").json()["items"]}
    assert rec == {"Bread": "dinner", "Peanut Butter": None}
    assert {i["meal"] for i in b.get("/api/quick/recent").json()["items"]} == {"lunch"}


def test_quick_favorite_never_logged_has_null_meal(a):
    f = food(a, BREAD)
    a.post(f"/api/favorites/{f['id']}")
    assert a.get("/api/quick/favorites").json()["items"][0]["meal"] is None


def test_quick_yesterday_one_item_per_food_and_meal(a):
    bread, pb = food(a, BREAD), food(a, PB)
    log(a, bread, 1, day="2025-03-01", meal="breakfast")
    log(a, pb, 1, "tbsp", day="2025-03-01", meal="lunch")
    log(a, bread, 2, day="2025-03-01", meal="dinner")
    log(a, bread, 3, day="2025-03-01", meal="breakfast")  # same pair again: last one wins
    log(a, bread, 1, day="2025-03-02", meal="snack")  # not yesterday
    items = a.get("/api/quick/yesterday", params={"day": "2025-03-02"}).json()["items"]
    assert [(i["food"]["name"], i["meal"], i["amount"]) for i in items] == [
        ("Peanut Butter", "lunch", 1), ("Bread", "dinner", 2), ("Bread", "breakfast", 3)]


def test_recipe_meal_from_post_and_validation(a):
    f = food(a, BREAD)
    items = [{"food_id": f["id"], "amount": 1, "unit": "slice"}]
    m = a.post("/api/meals", json={"name": "Lunch box", "items": items, "meal": "lunch"}).json()
    assert m["meal"] == "lunch" and m["meals"] == ["lunch"]
    plain = a.post("/api/meals", json={"name": "Plain", "items": items}).json()
    assert plain["meal"] is None and plain["meals"] == []
    assert a.post("/api/meals", json={"name": "x", "items": items, "meal": "brunch"}).status_code == 400
    listed = {r["name"]: r for r in a.get("/api/meals").json()["meals"]}
    assert listed["Lunch box"]["meals"] == ["lunch"] and listed["Plain"]["meals"] == []


def test_recipe_from_day_sets_meal_only_when_entries_agree(a):
    bread, pb = food(a, BREAD), food(a, PB)
    e1 = log(a, bread, day="2025-03-01", meal="breakfast")
    e2 = log(a, pb, 1, "tbsp", day="2025-03-01", meal="breakfast")
    e3 = log(a, bread, day="2025-03-01", meal="dinner")
    same = a.post("/api/meals/from-day", json={"name": "A", "day": "2025-03-01", "entry_ids": [e1["id"], e2["id"]]}).json()
    assert same["meal"] == "breakfast" and same["meals"] == ["breakfast"]
    mixed = a.post("/api/meals/from-day", json={"name": "B", "day": "2025-03-01"}).json()
    assert mixed["meal"] is None and mixed["meals"] == []
    one = a.post("/api/meals/from-day", json={"name": "C", "day": "2025-03-01", "entry_ids": [e3["id"]]}).json()
    assert one["meal"] == "dinner"
    log(a, bread, day="2025-03-03")
    assert a.post("/api/meals/from-day", json={"name": "D", "day": "2025-03-03"}).json()["meal"] is None


def test_init_adds_meal_column_to_an_old_meals_table(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.execute("CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), "
                  "name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        c.execute("INSERT INTO meals(user_id, name) VALUES (1, 'Old')")
    for _ in range(2):  # safe to run again
        with db.conn() as c:
            core.init(c)
    with db.conn() as c:
        assert c.execute("SELECT name, meal FROM meals").fetchall()[0]["meal"] is None
        assert [r[1] for r in c.execute("PRAGMA table_info(meals)")].count("meal") == 1


# ---------- goals and settings ----------

def test_goals_default_put_and_isolation(a, b):
    assert a.get("/api/goals").json() == {"kcal": 3000, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20}
    new = {"kcal": 2000, "carb_pct": 40, "protein_pct": 30, "fat_pct": 30}
    assert a.put("/api/goals", json=new).json() == new
    assert a.get("/api/goals").json() == new
    assert b.get("/api/goals").json()["kcal"] == 3000
    t = a.get("/api/day").json()["targets"]
    assert t == {"kcal": 2000, "carbs": 200, "protein": 150, "fat": 66.7}
    assert b.get("/api/day").json()["targets"]["kcal"] == 3000


@pytest.mark.parametrize("patch", [{"fat_pct": 25}, {"kcal": 0}, {"kcal": -5}, {"carb_pct": -10, "fat_pct": 40},
                                   {"kcal": "x"}, {"kcal": None}])
def test_goals_validation(a, patch):
    good = {"kcal": 2000, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20}
    assert a.put("/api/goals", json=good | patch).status_code == 400
    assert a.get("/api/goals").json()["kcal"] == 3000


def test_settings_default_put_validate_and_isolation(a, b):
    d = {"start_screen": "today", "default_meal": None, "use_last": True, "confirm_ai": True, "amount_format": "fraction",
         "full_claude": False}
    assert a.get("/api/settings").json() == d
    r = a.put("/api/settings", json={"start_screen": "scan", "default_meal": "lunch"})
    assert r.json() == d | {"start_screen": "scan", "default_meal": "lunch"}
    assert a.put("/api/settings", json={"default_meal": None}).json() == d | {"start_screen": "scan"}
    assert b.get("/api/settings").json() == d
    for body in ({"start_screen": "home"}, {"default_meal": "brunch"}, {"start_screen": None}):
        assert a.put("/api/settings", json=body).status_code == 400
    assert a.get("/api/settings").json()["start_screen"] == "scan"
    for s in ("today", "scan", "search", "ai"):
        assert a.put("/api/settings", json={"start_screen": s}).status_code == 200


def test_use_last_persists_and_is_per_user(a, b):
    assert a.get("/api/settings").json()["use_last"] is True
    r = a.put("/api/settings", json={"use_last": False})
    assert r.json()["use_last"] is False
    assert a.get("/api/settings").json()["use_last"] is False
    assert b.get("/api/settings").json()["use_last"] is True
    # other settings keep their values and the flag survives them
    a.put("/api/settings", json={"start_screen": "search"})
    assert a.get("/api/settings").json() == {"start_screen": "search", "default_meal": None, "use_last": False,
                                             "confirm_ai": True, "amount_format": "fraction", "full_claude": False}
    assert a.put("/api/settings", json={"use_last": True}).json()["use_last"] is True
    assert a.get("/api/settings").json()["use_last"] is True


@pytest.mark.parametrize("v", ["yes", "false", 0, 1, None, [], {}])
def test_use_last_invalid_value_400(a, v):
    assert a.put("/api/settings", json={"use_last": v}).status_code == 400
    assert a.get("/api/settings").json()["use_last"] is True


def test_use_last_column_is_added_to_an_old_settings_table(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "old.db")
    c.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY);"
                    "CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT);"
                    "INSERT INTO settings(user_id,start_screen) VALUES(1,'scan');")
    core.init(c)
    core.init(c)  # running twice is harmless
    assert c.execute("SELECT start_screen, use_last FROM settings").fetchone() == ("scan", 1)


def test_confirm_ai_persists_per_user_and_is_boolean(a, b):
    assert a.get("/api/settings").json()["confirm_ai"] is True
    assert a.put("/api/settings", json={"confirm_ai": False}).json()["confirm_ai"] is False
    assert a.get("/api/settings").json()["confirm_ai"] is False
    assert b.get("/api/settings").json()["confirm_ai"] is True
    a.put("/api/settings", json={"use_last": False})  # other settings keep it
    assert a.get("/api/settings").json()["confirm_ai"] is False


@pytest.mark.parametrize("v", ["yes", "false", 0, 1, None, [], {}])
def test_confirm_ai_invalid_value_400(a, v):
    assert a.put("/api/settings", json={"confirm_ai": v}).status_code == 400
    assert a.get("/api/settings").json()["confirm_ai"] is True


def test_amount_format_persists_per_user(a, b):
    assert a.get("/api/settings").json()["amount_format"] == "fraction"
    assert a.put("/api/settings", json={"amount_format": "decimal"}).json()["amount_format"] == "decimal"
    assert a.get("/api/settings").json()["amount_format"] == "decimal"
    assert b.get("/api/settings").json()["amount_format"] == "fraction"
    a.put("/api/settings", json={"confirm_ai": False})
    assert a.get("/api/settings").json()["amount_format"] == "decimal"
    assert a.put("/api/settings", json={"amount_format": "fraction"}).json()["amount_format"] == "fraction"


@pytest.mark.parametrize("v", ["fractions", "Decimal", "", None, 1, True, []])
def test_amount_format_invalid_value_400(a, v):
    assert a.put("/api/settings", json={"amount_format": v}).status_code == 400
    assert a.get("/api/settings").json()["amount_format"] == "fraction"


def test_new_settings_columns_are_added_to_an_old_settings_table(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "old2.db")
    c.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY);"
                    "CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT,"
                    " use_last INTEGER NOT NULL DEFAULT 1);"
                    "INSERT INTO settings(user_id,start_screen) VALUES(1,'scan');")
    core.init(c)
    core.init(c)
    assert c.execute("SELECT start_screen, confirm_ai, amount_format FROM settings").fetchone() == ("scan", 1, "fraction")


def test_every_route_requires_current_user(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    api = FastAPI()
    api.include_router(core.router)

    def deny():
        raise HTTPException(401, "Not signed in")

    api.dependency_overrides[deps.current_user] = deny
    client = TestClient(api)
    assert len(core.router.routes) >= 20
    for route in core.router.routes:
        path = route.path.replace("{code}", "1").replace("{food_id}", "1").replace("{entry_id}", "1").replace("{meal_id}", "1")
        for method in route.methods:
            assert client.request(method, path, json={}).status_code == 401, (method, path)


# ---------- serving and percent units ----------

def test_units_listed_after_label_unit(a):
    f = food(a)
    us = [u["unit"] for u in a.get(f"/api/foods/{f['id']}").json()["units"]]
    assert us[:4] == ["slice", "serving", "pct", "g"]


def test_preview_serving_and_pct(a):
    f = food(a)
    p = a.get("/api/preview", params={"food_id": f["id"], "amount": "0.5", "unit": "serving"}).json()
    assert p["servings"] == 0.5 and p["estimated"] is False and p["kcal"] == round(BREAD["kcal"] * 0.5, 2)
    p = a.get("/api/preview", params={"food_id": f["id"], "amount": "25", "unit": "%"}).json()
    assert p["servings"] == 0.25 and p["kcal"] == round(BREAD["kcal"] * 0.25, 2)
    assert a.get("/api/preview", params={"food_id": f["id"], "amount": "0", "unit": "pct"}).status_code == 400


def test_entries_with_serving_and_pct_round_trip(a):
    f = food(a)
    day = "2025-04-01"
    e1 = log(a, f, 0.5, "servings", day=day)
    e2 = log(a, f, 25, "percent", day=day)
    assert (e1["amount"], e1["unit"], e1["servings"]) == (0.5, "serving", 0.5)
    assert (e2["amount"], e2["unit"], e2["servings"]) == (25, "pct", 0.25)
    d = a.get("/api/day", params={"day": day}).json()
    assert [(e["amount"], e["unit"]) for e in d["entries"]] == [(0.5, "serving"), (25, "pct")]
    assert d["totals"]["kcal"] == pytest.approx(round(BREAD["kcal"] * 0.5, 2) + round(BREAD["kcal"] * 0.25, 2))
    assert a.get(f"/api/foods/{f['id']}").json()["last"] == {"amount": 25, "unit": "pct"}


def test_patch_entry_to_and_from_pseudo_units(a):
    f = food(a)
    e = log(a, f, 2, "slice", day="2025-04-01")
    r = a.patch(f"/api/entries/{e['id']}", json={"amount": 50, "unit": "pct"}).json()
    assert (r["amount"], r["unit"], r["servings"]) == (50, "pct", 0.5)
    assert r["kcal"] == round(BREAD["kcal"] * 0.5, 2)
    r = a.patch(f"/api/entries/{e['id']}", json={"amount": 1.5}).json()  # unit stays pct
    assert (r["unit"], r["servings"]) == ("pct", 0.015)
    r = a.patch(f"/api/entries/{e['id']}", json={"amount": 0.75, "unit": "serving"}).json()
    assert (r["amount"], r["unit"], r["servings"]) == (0.75, "serving", 0.75)


def test_quick_items_and_meals_keep_pseudo_units(a):
    f = food(a)
    log(a, f, 25, "pct", day="2025-04-01")
    for url in ("/api/quick/recent", "/api/quick/yesterday?day=2025-04-02"):
        it = a.get(url).json()["items"][0]
        assert (it["amount"], it["unit"], it["servings"]) == (25, "pct", 0.25)
    a.post(f"/api/favorites/{f['id']}")
    assert a.get("/api/quick/favorites").json()["items"][0]["unit"] == "pct"
    m = a.post("/api/meals", json={"name": "Bit", "items": [{"food_id": f["id"], "amount": 0.5, "unit": "serving"}]})
    assert m.status_code == 200, m.text
    assert m.json()["items"][0]["servings"] == 0.5
    r = a.post(f"/api/meals/{m.json()['id']}/log", json={"day": "2025-04-03"})
    assert r.status_code == 200, r.text
    d = a.get("/api/day", params={"day": "2025-04-03"}).json()
    assert [(e["amount"], e["unit"]) for e in d["entries"][0]["parts"]] == [(0.5, "serving")]  # one recipe log, its rows inside
    r = a.post(f"/api/meals/{m.json()['id']}/log",
               json={"day": "2025-04-03", "items": [{"food_id": f["id"], "amount": 50, "unit": "%"}]})
    assert r.status_code == 200, r.text
    d = a.get("/api/day", params={"day": "2025-04-03"}).json()
    part = d["entries"][-1]["parts"][-1]
    assert (part["amount"], part["unit"]) == (50, "pct")


def test_recipe_from_meal_tags_and_validates(a, b):
    bread, pb = food(a, BREAD), food(a, PB)
    e1 = log(a, bread, day="2025-03-01", meal="breakfast")
    e2 = log(a, pb, 1, "tbsp", day="2025-03-01", meal="breakfast")
    e3 = log(a, bread, day="2025-03-01", meal="dinner")
    e4 = log(a, pb, 2, "tbsp", day="2025-03-01")
    url = "/api/meals/from-meal"
    base = {"name": "Toast", "day": "2025-03-01", "meal": "breakfast"}
    m = a.post(url, json=base | {"entry_ids": [e2["id"]]}).json()
    assert [i["food_id"] for i in m["items"]] == [pb["id"]] and m["meal"] == "breakfast" and m["meals"] == ["breakfast"]
    both = a.post(url, json=base | {"entry_ids": [e1["id"], e2["id"]]}).json()
    assert len(both["items"]) == 2
    un = a.post(url, json={"name": "Misc", "day": "2025-03-01", "meal": None, "entry_ids": [e4["id"]]}).json()
    assert un["meal"] is None and un["meals"] == []
    for bad_body in (base | {"entry_ids": []}, base, base | {"entry_ids": [e3["id"]]},  # empty, missing, other meal
                     base | {"entry_ids": [999]}, base | {"entry_ids": [e1["id"]], "day": "2025-03-02"},
                     base | {"entry_ids": [e1["id"]], "meal": "brunch"}, base | {"entry_ids": [e1["id"]], "name": " "}):
        assert a.post(url, json=bad_body).status_code == 400
    assert b.post(url, json=base | {"entry_ids": [e1["id"]]}).status_code == 400  # not their entry
