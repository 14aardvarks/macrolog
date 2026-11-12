"""Imported recipes: unmatched ingredients, matching row by row, skipping, totals and the loggability rule."""
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


def test_match_skip_totals_and_logging_rule(a, b):
    m = imported(a)
    bread, pb = food(a), food(a, PB)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}"
    assert a.post(url + "/log", json={}).status_code == 409
    r = a.patch(f"{url}/items/{ids[0]}", json={"food_id": bread["id"], "amount": 2, "unit": "slice"}).json()
    assert (r["matched"], r["needed"], r["kcal"]) == (1, 3, 180)
    assert r["items"][0]["food"]["name"] == "Bread" and r["items"][0]["src"]["text"] == "2 slices bread"
    # bad unit for the food, other user's recipe, unknown item, partial bodies
    assert a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 4, "unit": "slice"}).status_code == 400
    assert b.patch(f"{url}/items/{ids[1]}", json={"skipped": True}).status_code == 404
    assert a.patch(f"{url}/items/999", json={"skipped": True}).status_code == 404
    assert a.patch(f"{url}/items/{ids[1]}", json={"amount": 1}).status_code == 400
    assert a.patch(f"{url}/items/{ids[1]}", json={"skipped": "yes"}).status_code == 400
    assert a.patch(f"{url}/items/{ids[1]}", json={}).status_code == 400
    r = a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 4, "unit": "tbsp"}).json()
    assert (r["matched"], r["complete"], r["kcal"]) == (2, False, 560)
    assert r["per_serving"]["kcal"] == 280 and r["totals"]["fiber"] == 10
    assert a.post(url + "/log", json={}).status_code == 409  # salt is still open
    r = a.patch(f"{url}/items/{ids[2]}", json={"skipped": True}).json()
    assert (r["matched"], r["needed"], r["skipped"], r["complete"]) == (2, 2, 1, True)
    logged = a.post(url + "/log", json={"meal": "lunch"}).json()["entries"]
    assert [e["name"] for e in logged] == ["Bread", "Peanut Butter"]
    # unmatch makes it unloggable again; matching a skipped row un-skips it
    r = a.patch(f"{url}/items/{ids[0]}", json={"food_id": None}).json()
    assert r["items"][0]["food"] is None and r["items"][0]["amount"] is None and not r["complete"]
    r = a.patch(f"{url}/items/{ids[2]}", json={"food_id": bread["id"], "amount": 1, "unit": "slice"}).json()
    assert r["items"][2]["skipped"] is False


def test_all_skipped_cannot_be_logged_and_items_replace_waits(a):
    m = imported(a, rows=[{"name": "water"}])
    url = f"/api/meals/{m['id']}"
    a.patch(f"{url}/items/{m['items'][0]['id']}", json={"skipped": True})
    assert a.post(url + "/log", json={}).status_code == 409
    f = food(a)
    r = a.patch(url, json={"items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]})
    assert r.status_code == 409
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
    assert a.post(url + "/log", json={}).status_code == 409
    assert a.patch(url, json={"items": [{"food_id": bread["id"], "amount": 1, "unit": "slice"}]}).status_code == 409
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
