"""Imported recipes: unmatched ingredients, matching row by row, skipping, totals and partial recipes that log."""
import sqlite3

import pytest

from app import core, db
from tests.test_core import BREAD, PB, a, b, env, food  # noqa: F401

ROWS = [{"text": "2 slices bread", "amount": 2, "unit": "slice", "name": "bread"},
        {"amount": 4, "unit": "tbsp", "name": "peanut butter", "note": "smooth"},
        {"name": "salt", "note": "to taste"}]


def imported(client, rows=ROWS, **kw):
    r = client.post("/api/meals/import", json={"name": "PB Toast", "servings": 2, "meals": ["lunch"], "ingredients": rows, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_saves_every_row_unmatched(a, b):
    m = imported(a)
    assert (m["matched"], m["needed"], m["skipped"], m["complete"], m["servings"], m["meals"]) == (0, 3, 0, False, 2, ["lunch"])
    assert [i["src"]["text"] for i in m["items"]] == ["2 slices bread", "4 tbsp peanut butter, smooth", "salt, to taste"]
    assert m["items"][1]["src"] == {"text": "4 tbsp peanut butter, smooth", "amount": 4, "unit": "tbsp", "name": "peanut butter", "note": "smooth"}
    assert all(i["food"] is None and i["kcal"] is None and not i["matched"] for i in m["items"])
    assert m["kcal"] == 0 and m["totals"]["fiber"] is None
    assert a.get(f"/api/meals/{m['id']}").json()["id"] == m["id"]
    assert b.get(f"/api/meals/{m['id']}").status_code == 404
    assert any(x["id"] == m["id"] for x in a.get("/api/meals").json()["meals"])


@pytest.mark.parametrize("body", [
    {"name": "", "ingredients": ROWS}, {"name": "R", "ingredients": []}, {"name": "R", "ingredients": "x"},
    {"name": "R", "ingredients": [{"amount": 1}]}, {"name": "R", "ingredients": [{"name": "x", "amount": -1}]},
    {"name": "R", "ingredients": [{"name": "x", "evil": 1}]}, {"name": "R", "servings": 0, "ingredients": ROWS},
    {"name": "R", "servings": 5000, "ingredients": ROWS}, {"name": "R", "meals": ["brunch"], "ingredients": ROWS},
    {"name": "R", "ingredients": [{"name": "x" * 201}]}, {"name": "R", "ingredients": [{"name": "x"}] * 101},
    {"name": "R", "ingredients": [{"name": "x", "unit": 5}]},
])
def test_import_validation(a, body):
    assert a.post("/api/meals/import", json=body).status_code == 400


def test_match_skip_totals_and_partial_logging(a, b):
    m = imported(a)
    bread, pb = food(a), food(a, PB)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}"
    r = a.post(url + "/log", json={})
    assert r.status_code == 400 and r.json()["detail"] == "Match at least one ingredient to log this recipe."
    r = a.patch(f"{url}/items/{ids[0]}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"}).json()
    assert (r["matched"], r["needed"], r["kcal"]) == (1, 3, 180)
    assert r["items"][0]["food"]["name"] == "Bread" and r["items"][0]["src"]["text"] == "2 slices bread"
    # bad unit for the food, other user's recipe, unknown item, partial bodies
    assert a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 4, "unit": "x" * 31}).status_code == 400
    assert b.patch(f"{url}/items/{ids[1]}", json={"skipped": True}).status_code == 404
    assert a.patch(f"{url}/items/999", json={"skipped": True}).status_code == 404
    assert a.patch(f"{url}/items/{ids[1]}", json={"amount": 1}).status_code == 400
    assert a.patch(f"{url}/items/{ids[1]}", json={"skipped": "yes"}).status_code == 400
    assert a.patch(f"{url}/items/{ids[1]}", json={}).status_code == 400
    r = a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 4, "unit": "tbsp"}).json()
    assert (r["matched"], r["complete"], r["kcal"]) == (2, False, 560)
    assert r["per_serving"]["kcal"] == 280 and r["totals"]["fiber"] == 10
    assert a.post(url + "/log", json={}).status_code == 200  # salt is still open, and that is fine
    r = a.patch(f"{url}/items/{ids[2]}", json={"skipped": True}).json()
    assert (r["matched"], r["needed"], r["skipped"], r["complete"]) == (2, 2, 1, True)
    logged = a.post(url + "/log", json={"meal": "lunch"}).json()["entries"]
    assert [e["name"] for e in logged] == ["Bread", "Peanut Butter"]
    # unmatching one of two matched rows still logs the other; matching a skipped row un-skips it
    r = a.patch(f"{url}/items/{ids[0]}", json={"food_id": None}).json()
    assert r["items"][0]["food"] is None and r["items"][0]["amount"] is None and not r["complete"]
    r = a.patch(f"{url}/items/{ids[2]}", json={"food_id": bread["id"], "amount": 1, "unit": "slice"}).json()
    assert r["items"][2]["skipped"] is False


def test_all_skipped_cannot_be_logged_and_items_replace_keeps_reference_lines(a):
    m = imported(a, rows=[{"name": "water"}])
    url = f"/api/meals/{m['id']}"
    a.patch(f"{url}/items/{m['items'][0]['id']}", json={"skipped": True})
    assert a.post(url + "/log", json={}).status_code == 400
    f = food(a)
    r = a.patch(url, json={"items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]})
    assert r.status_code == 200
    assert [(i["src"]["name"] if i["src"] else None, i["skipped"], i["food_id"]) for i in r.json()["items"]] == [(None, False, f["id"]), ("water", True, None)]
    assert a.patch(url, json={"servings": 4}).json()["servings"] == 4
    assert a.patch(url, json={"servings": None}).json()["servings"] == 1
    assert a.patch(url, json={"servings": -1}).status_code == 400


def test_regular_recipes_are_complete(a):
    f = food(a)
    m = a.post("/api/meals", json={"name": "R", "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).json()
    assert (m["complete"], m["matched"], m["needed"], m["servings"], m["items"][0]["src"]) == (True, 1, 1, 1, None)


def test_old_meal_items_table_is_migrated_once(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.executescript("""
        CREATE TABLE foods(id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT, name TEXT NOT NULL, brand TEXT,
          serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL, serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',
          kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL, UNIQUE(source, source_id));
        CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT);
        CREATE TABLE meal_items(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
          food_id INTEGER NOT NULL REFERENCES foods(id), amount REAL NOT NULL, unit TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0);
        INSERT INTO users(id, username) VALUES (1, 'a');
        INSERT INTO foods VALUES (1, 'custom', NULL, NULL, 'Bread', NULL, 1, 'slice', 34, NULL, '1 slice', 90, 17, 4, 1.5, 3);
        INSERT INTO meals VALUES (7, 1, 'Toast', NULL);
        INSERT INTO meal_items VALUES (5, 7, 1, 2, 'slice', 3);
        """)
    for _ in range(2):  # running init twice is safe
        with db.conn() as c:
            core.init(c)
    with db.conn() as c:
        cols = {r[1]: r for r in c.execute("PRAGMA table_info(meal_items)")}
        assert cols["food_id"][3] == 0 and "src_text" in cols and "skipped" in cols
        assert dict(c.execute("SELECT id, meal_id, food_id, amount, unit, position FROM meal_items").fetchone()) == \
            {"id": 5, "meal_id": 7, "food_id": 1, "amount": 2, "unit": "slice", "position": 3}
        assert "meal_items_new" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
        m = core.meal_dict(c, c.execute("SELECT * FROM meals WHERE id=7").fetchone())
        assert m["kcal"] == 180 and m["complete"]
        c.execute("DELETE FROM meals WHERE id=7")  # the cascade still works after the rebuild
        assert c.execute("SELECT COUNT(*) FROM meal_items").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO meal_items(meal_id, food_id) VALUES (999, NULL)")


# ---------- recipe steps ----------

STEPS = ["Preheat the oven to 350 F.", "  Mix the   dry ingredients. ", "", "Bake 20 minutes."]


def test_steps_on_import_create_and_patch(a, b):
    m = imported(a, steps=STEPS)
    assert m["steps"] == ["Preheat the oven to 350 F.", "Mix the dry ingredients.", "Bake 20 minutes."]
    assert imported(a)["steps"] == []
    url = f"/api/meals/{m['id']}"
    # steps can change while ingredients are still unmatched, and never touch nutrition or completeness
    r = a.patch(url, json={"steps": ["Mix.", "Bake."]}).json()
    assert r["steps"] == ["Mix.", "Bake."] and (r["matched"], r["kcal"], r["complete"]) == (0, 0, False)
    assert a.patch(url, json={"steps": []}).json()["steps"] == []
    assert b.patch(url, json={"steps": ["x"]}).status_code == 404
    f = food(a)
    made = a.post("/api/meals", json={"name": "R", "steps": ["Toast it."], "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).json()
    assert made["steps"] == ["Toast it."] and made["kcal"] == 90
    assert a.get(f"/api/meals/{made['id']}").json()["steps"] == ["Toast it."]
    entries = a.post(f"/api/meals/{made['id']}/log", json={}).json()["entries"]
    assert [e["name"] for e in entries] == ["Bread"]  # steps are not logged


def test_from_meal_recipes_start_without_steps(a):
    f = food(a)
    e = a.post("/api/entries", json={"food_id": f["id"], "amount": 1, "unit": "slice", "day": "2025-01-02", "meal": "lunch"}).json()
    m = a.post("/api/meals/from-meal", json={"name": "Lunch", "day": "2025-01-02", "meal": "lunch", "entry_ids": [e["id"]]}).json()
    assert m["steps"] == []
    assert a.patch(f"/api/meals/{m['id']}", json={"steps": ["Eat."]}).json()["steps"] == ["Eat."]


@pytest.mark.parametrize("steps", ["Mix", [1], ["x" * (core.MAX_STEP_LEN + 1)], ["x"] * (core.MAX_STEPS + 1), {"a": 1}])
def test_steps_validation(a, steps):
    f = food(a)
    assert a.post("/api/meals/import", json={"name": "R", "ingredients": ROWS, "steps": steps}).status_code == 400
    assert a.post("/api/meals", json={"name": "R", "steps": steps, "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).status_code == 400
    m = imported(a)
    assert a.patch(f"/api/meals/{m['id']}", json={"steps": steps}).status_code == 400


def test_steps_limits_are_inclusive(a):
    m = imported(a, steps=["x" * core.MAX_STEP_LEN] * core.MAX_STEPS)
    assert len(m["steps"]) == core.MAX_STEPS


# ---------- Check Amount ----------

def test_check_amount_rows_count_for_nothing_until_confirmed(a):
    m = imported(a)
    bread, pb = food(a), food(a, PB)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}"
    a.patch(f"{url}/items/{ids[0]}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"})
    a.patch(f"{url}/items/{ids[2]}", json={"skipped": True})
    r = a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 2, "unit": "tbsp", "check": True}).json()
    row = r["items"][1]
    assert row["check"] is True and row["matched"] is False and row["food"]["name"] == "Peanut Butter" and row["kcal"] == 190
    assert (r["matched"], r["needed"], r["checks"], r["complete"], r["kcal"]) == (1, 2, 1, False, 180)
    assert a.post(url + "/log", json={}).status_code == 200  # the unconfirmed row is simply not logged
    # confirming is a plain match without check
    r = a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 4, "unit": "tbsp"}).json()
    assert (r["items"][1]["check"], r["matched"], r["checks"], r["complete"], r["kcal"]) == (False, 2, 0, True, 560)
    assert r["items"][1]["grams"] == 64 and r["items"][0]["grams"] == 68
    assert a.post(url + "/log", json={}).status_code == 200
    # unmatching clears the flag too
    a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 1, "unit": "tbsp", "check": True})
    r = a.patch(f"{url}/items/{ids[1]}", json={"food_id": None}).json()
    assert r["items"][1]["check"] is False and r["checks"] == 0


@pytest.mark.parametrize("body", [{"check": True}, {"food_id": None, "check": True}, {"food_id": 1, "amount": 1, "unit": "slice", "check": "yes"}])
def test_check_validation(a, body):
    m = imported(a)
    food(a)
    assert a.patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json=body).status_code == 400


def test_old_databases_get_steps_and_needs_check(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old2.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.executescript("""
        CREATE TABLE foods(id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT, name TEXT NOT NULL, brand TEXT,
          serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL, serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',
          kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL, UNIQUE(source, source_id));
        CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT, meal TEXT, servings REAL);
        CREATE TABLE meal_items(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
          food_id INTEGER REFERENCES foods(id), amount REAL, unit TEXT, position INTEGER NOT NULL DEFAULT 0,
          src_text TEXT, src_amount REAL, src_unit TEXT, src_name TEXT, src_note TEXT, skipped INTEGER NOT NULL DEFAULT 0);
        INSERT INTO users(id, username) VALUES (1, 'a');
        INSERT INTO meals(id, user_id, name) VALUES (3, 1, 'Soup');
        INSERT INTO meal_items(id, meal_id, src_text, src_name) VALUES (4, 3, '1 onion', 'onion');
        """)
    for _ in range(2):
        with db.conn() as c:
            core.init(c)
    with db.conn() as c:
        m = core.meal_dict(c, c.execute("SELECT * FROM meals WHERE id=3").fetchone())
        assert m["steps"] == [] and m["items"][0]["check"] is False and m["checks"] == 0
        c.execute("UPDATE meals SET steps='not json' WHERE id=3")
        assert core.meal_dict(c, c.execute("SELECT * FROM meals WHERE id=3").fetchone())["steps"] == []


# ---------- editing a finished recipe on Match Ingredients: add, remove, unmatch ----------

def finished(a, count=2):
    bread, pb = food(a), food(a, PB)
    items = [{"food_id": bread["id"], "amount": 2, "unit": "slice"}, {"food_id": pb["id"], "amount": 4, "unit": "tbsp"}][:count]
    return a.post("/api/meals", json={"name": "Toast", "items": items}).json(), bread, pb


def test_unmatching_a_hand_built_row_keeps_a_line_to_search_for(a):
    m, bread, pb = finished(a)
    assert m["items"][0]["src"] is None
    r = a.patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"food_id": None}).json()
    it = r["items"][0]
    assert it["food"] is None and it["src"] == {"text": "Bread", "amount": 2, "unit": "slice", "name": "Bread", "note": None}
    assert (r["matched"], r["needed"], r["complete"]) == (1, 2, False)
    # an imported row keeps its own line
    imp = imported(a)
    i0 = imp["items"][0]
    a.patch(f"/api/meals/{imp['id']}/items/{i0['id']}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"})
    back = a.patch(f"/api/meals/{imp['id']}/items/{i0['id']}", json={"food_id": None}).json()["items"][0]
    assert back["src"]["text"] == "2 slices bread"


def test_add_a_line_a_matched_row_and_position(a, b):
    m, bread, pb = finished(a)
    url = f"/api/meals/{m['id']}/items"
    r = a.post(url, json={"src": {"name": "olive oil", "amount": 1, "unit": "tbsp"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["id"] for i in body["items"]][-1] == body["added"] and len(body["items"]) == 3
    new = body["items"][2]
    assert new["food"] is None and new["src"]["text"] == "1 tbsp olive oil" and new["src"]["name"] == "olive oil"
    assert (body["matched"], body["needed"], body["complete"]) == (2, 3, False)
    # a matched row, put in at a position
    r = a.post(url, json={"food_id": bread["id"], "amount": 1, "unit": "slice", "position": 0, "src": {"name": "bread", "text": "1 slice bread"}}).json()
    assert [i["id"] for i in r["items"]][0] == r["added"] and r["items"][0]["matched"] and r["items"][0]["src"]["text"] == "1 slice bread"
    assert [i["food_id"] for i in r["items"]] == [bread["id"], bread["id"], pb["id"], None]
    # skipped and check restore
    r = a.post(url, json={"food_id": pb["id"], "amount": 1, "unit": "tbsp", "check": True, "skipped": True, "position": 99}).json()
    last = r["items"][-1]
    assert last["id"] == r["added"] and last["check"] and last["skipped"]
    assert b.post(url, json={"src": {"name": "x"}}).status_code == 404
    assert a.get(f"/api/meals/{m['id']}").json()["items"][0]["src"]["text"] == "1 slice bread"


@pytest.mark.parametrize("body", [{}, {"amount": 1}, {"src": {}}, {"src": {"name": ""}}, {"src": {"name": "x", "evil": 1}}, {"src": "x"},
                                  {"src": {"name": "x"}, "position": -1}, {"src": {"name": "x"}, "position": "a"}, {"src": {"name": "x"}, "skipped": "y"},
                                  {"src": {"name": "x"}, "check": True}, {"src": {"name": "x"}, "amount": 1}, {"food_id": 999, "amount": 1, "unit": "slice"},
                                  {"food_id": 1, "amount": 1, "unit": "banana" * 6}, {"src": {"name": "x"}, "extra": 1}])
def test_add_item_validation(a, body):
    m, bread, pb = finished(a)
    assert a.post(f"/api/meals/{m['id']}/items", json=body).status_code in (400, 404)
    assert len(a.get(f"/api/meals/{m['id']}").json()["items"]) == 2


def test_add_item_cap_and_remove(a, b):
    m, bread, pb = finished(a)
    url = f"/api/meals/{m['id']}/items"
    ids = [i["id"] for i in m["items"]]
    r = a.delete(f"{url}/{ids[0]}")
    assert r.status_code == 200 and [i["id"] for i in r.json()["items"]] == [ids[1]] and r.json()["kcal"] == 380
    assert a.delete(f"{url}/{ids[1]}").status_code == 409  # the last row stays
    assert a.delete(f"{url}/{ids[0]}").status_code == 404
    assert b.delete(f"{url}/{ids[1]}").status_code == 404
    full = a.post("/api/meals/import", json={"name": "Big", "ingredients": [{"name": f"x{i}"} for i in range(100)]}).json()
    assert a.post(f"/api/meals/{full['id']}/items", json={"src": {"name": "one more"}}).status_code == 409


def test_a_removed_row_can_be_put_back_where_it_was(a):
    m, bread, pb = finished(a)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}/items"
    a.delete(f"{url}/{ids[0]}")
    r = a.post(url, json={"food_id": bread["id"], "amount": 2, "unit": "slice", "position": 0}).json()
    assert [i["food_id"] for i in r["items"]] == [bread["id"], pb["id"]] and r["kcal"] == 560 and r["complete"]


def test_partial_recipe_logs_only_matched_rows(a):
    m = imported(a, rows=[*ROWS, {"name": "pepper"}, {"name": "cumin"}])
    bread, pb = food(a), food(a, PB)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}"
    a.patch(f"{url}/items/{ids[0]}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"})
    a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 2, "unit": "tbsp", "check": True})  # never confirmed
    a.patch(f"{url}/items/{ids[2]}", json={"skipped": True})
    r = a.get(url).json()
    assert (r["matched"], r["needed"], r["skipped"], r["checks"], r["complete"]) == (1, 4, 1, 1, False)
    assert r["kcal"] == 180 and r["totals"]["fiber"] == 6 and r["per_serving"]["kcal"] == 90
    logged = a.post(url + "/log", json={"meal": "lunch"}).json()["entries"]
    assert [e["name"] for e in logged] == ["Bread"] and logged[0]["kcal"] == 180
    # a share of the recipe scales the matched rows only
    half = a.post(url + "/log", json={"amount": 1, "unit": "serving"}).json()["entries"]
    assert [e["name"] for e in half] == ["Bread"] and half[0]["kcal"] == 90
    # the checklist can still replace amounts; unmatched, skipped and check lines survive with no nutrition
    r = a.post(url + "/log", json={"items": [{"food_id": bread["id"], "amount": 1, "unit": "slice"}]})
    assert r.status_code == 200 and r.json()["entries"][0]["kcal"] == 90
    r = a.get(url).json()
    assert [i["src"]["text"] for i in r["items"]] == ["2 slices bread", "4 tbsp peanut butter, smooth", "salt, to taste", "pepper", "cumin"]
    assert [i["matched"] for i in r["items"]] == [True, False, False, False, False]
    assert r["items"][3]["food"] is None and r["items"][3]["kcal"] is None and r["kcal"] == 180
    # editing the matched row's amount leaves the reference lines alone
    r = a.patch(url, json={"items": [{"food_id": bread["id"], "amount": 4, "unit": "slice"}]}).json()
    assert [i["src"]["text"] if i["src"] else None for i in r["items"]] == [None, "4 tbsp peanut butter, smooth", "salt, to taste", "pepper", "cumin"]
    assert r["kcal"] == 360


def test_unmatched_rows_change_nothing_about_totals(a):
    full = imported(a, rows=ROWS[:1])
    part = imported(a, rows=[*ROWS[:1], {"name": "water"}, {"name": "x"}])
    bread = food(a)
    for m in (full, part):
        a.patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"})
    f, p = (a.get(f"/api/meals/{m['id']}").json() for m in (full, part))
    assert f["totals"] == p["totals"] and f["per_serving"] == p["per_serving"] and not p["complete"]
    assert len(a.post(f"/api/meals/{part['id']}/log", json={}).json()["entries"]) == 1


def test_save_without_them_removes_uncounted_rows_and_keep_leaves_them(a):
    rows = [*ROWS, {"name": "pepper"}]
    kept, dropped = imported(a, rows=rows), imported(a, rows=rows)
    bread, pb = food(a), food(a, PB)
    for m in (kept, dropped):
        u = f"/api/meals/{m['id']}"
        ids = [i["id"] for i in m["items"]]
        a.patch(f"{u}/items/{ids[0]}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"})
        a.patch(f"{u}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 2, "unit": "tbsp", "check": True})
        a.patch(f"{u}/items/{ids[2]}", json={"skipped": True})
    r = a.delete(f"/api/meals/{dropped['id']}/uncounted")
    assert r.status_code == 200
    d = r.json()
    assert [i["src"]["name"] for i in d["items"]] == ["bread"] and (d["matched"], d["needed"], d["complete"]) == (1, 1, True)
    k = a.get(f"/api/meals/{kept['id']}").json()
    assert len(k["items"]) == 4 and (k["matched"], k["needed"], k["complete"]) == (1, 3, False)
    assert k["totals"] == d["totals"] and k["per_serving"] == d["per_serving"]
    for m in (kept, dropped):
        e = a.post(f"/api/meals/{m['id']}/log", json={"meal": "lunch"}).json()["entries"]
        assert [x["name"] for x in e] == ["Bread"] and e[0]["kcal"] == 180
    assert a.delete(f"/api/meals/{dropped['id']}/uncounted").status_code == 200  # nothing left to remove


def test_save_without_them_needs_one_matched_row(a, b):
    m = imported(a)
    assert a.delete(f"/api/meals/{m['id']}/uncounted").status_code == 400
    assert len(a.get(f"/api/meals/{m['id']}").json()["items"]) == 3
    bread = food(a)
    a.patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"food_id": bread["id"], "amount": 1, "unit": "slice", "check": True})
    assert a.delete(f"/api/meals/{m['id']}/uncounted").status_code == 400  # an unconfirmed Check Amount row does not count
    assert b.delete(f"/api/meals/{m['id']}/uncounted").status_code == 404


def test_estimated_unit_row_counts_and_is_flagged_not_checked(a):
    m = imported(a, rows=[{"text": "1 cup oats", "amount": 1, "unit": "cup", "name": "oats"}])
    oats = a.post("/api/foods", json={"name": "Mystery Flakes", "serving_amount": 40, "serving_unit": "g", "kcal": 150, "carbs": 27, "protein": 5, "fat": 3}).json()
    pick = core.units.match_amount(oats, 1, "cup")
    assert pick == {"amount": 1, "unit": "cup", "check": False, "estimated": True}
    r = a.patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"food_id": oats["id"], "amount": pick["amount"], "unit": pick["unit"]}).json()
    row = r["items"][0]
    assert row["estimated"] is True and row["check"] is False and row["matched"] is True and r["complete"]
    assert r["kcal"] == round(150 * 236.588 / 40, 1)  # counted with the picker's 1 g per ml math
    assert len(a.post(f"/api/meals/{m['id']}/log", json={}).json()["entries"]) == 1
