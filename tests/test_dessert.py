"""Dessert as a fifth meal: logging, tagging, recipes, settings and older databases."""
import re
import sqlite3

from app import core, db
from tests.test_core import BREAD, PB, a, b, env, food, log  # noqa: F401


def fav(client, f):
    assert client.post(f"/api/favorites/{f['id']}").status_code == 200


def fav_item(client, f):
    return next(i for i in client.get("/api/quick/favorites").json()["items"] if i["food"]["id"] == f["id"])


def test_meals_order_ends_with_dessert():
    assert core.MEALS == ("breakfast", "lunch", "dinner", "snack", "dessert")


def test_log_and_patch_entry_with_dessert(a):
    f = food(a)
    e = log(a, f, meal="dessert", day="2025-05-01")
    assert e["meal"] == "dessert"
    day = a.get("/api/day", params={"day": "2025-05-01"}).json()
    assert [x["meal"] for x in day["entries"]] == ["dessert"]
    r = a.patch(f"/api/entries/{e['id']}", json={"meal": "snack"})
    assert r.status_code == 200 and r.json()["meal"] == "snack"
    assert a.patch(f"/api/entries/{e['id']}", json={"meal": "dessert"}).json()["meal"] == "dessert"
    assert a.post("/api/entries", json={"food_id": f["id"], "amount": 1, "unit": "slice", "meal": "Dessert"}).status_code == 400


def test_quick_lists_carry_dessert_meal(a):
    f = food(a)
    log(a, f, meal="dessert", day="2025-05-01")
    assert a.get("/api/quick/recent").json()["items"][0]["meal"] == "dessert"
    y = a.get("/api/quick/yesterday", params={"day": "2025-05-02"}).json()["items"]
    assert [i["meal"] for i in y] == ["dessert"]


def test_favorite_tags_and_auto_tag_with_dessert(a):
    f = food(a)
    fav(a, f)
    r = a.put(f"/api/favorites/{f['id']}/tags", json={"meals": ["dessert", "breakfast", "snack"]})
    assert r.json()["meals"] == ["breakfast", "snack", "dessert"]
    a.put(f"/api/favorites/{f['id']}/tags", json={"meals": []})
    log(a, f, meal="dessert")
    item = fav_item(a, f)
    assert item["meals"] == ["dessert"] and item["counts"] == {"dessert": 1}
    assert a.get("/api/saved").json()["favorites"][0]["meals"] == ["dessert"]


def test_hidden_food_unhides_when_logged_as_dessert(a):
    f = food(a)
    fav(a, f)
    a.post(f"/api/saved/favorites/{f['id']}/remove")
    assert a.get("/api/quick/recent").json()["items"] == []
    log(a, f, meal="dessert")
    assert [i["meal"] for i in a.get("/api/quick/recent").json()["items"]] == ["dessert"]


def test_recipe_tags_logs_and_from_meal_with_dessert(a):
    f, pb = food(a), food(a, PB)
    item = {"food_id": f["id"], "amount": 1, "unit": "slice"}
    m = a.post("/api/meals", json={"name": "Pie", "meals": ["dessert", "lunch"], "items": [item]}).json()
    assert m["meals"] == ["lunch", "dessert"]
    old = a.post("/api/meals", json={"name": "Old", "meal": "dessert", "items": [item]}).json()
    assert old["meals"] == ["dessert"] and old["meal"] == "dessert"
    r = a.post(f"/api/meals/{m['id']}/log", json={"meal": "dessert", "day": "2025-05-01"})
    assert r.status_code == 200
    got = a.get(f"/api/meals/{m['id']}").json()
    assert got["counts"] == {"dessert": 1}
    assert {e["meal"] for e in a.get("/api/day", params={"day": "2025-05-01"}).json()["entries"]} == {"dessert"}
    assert a.patch(f"/api/meals/{m['id']}", json={"meals": ["dessert"]}).json()["meals"] == ["dessert"]
    e = log(a, pb, 1, "tbsp", day="2025-05-02", meal="dessert")
    s = a.post("/api/meals/from-meal", json={"name": "Treat", "day": "2025-05-02", "meal": "dessert", "entry_ids": [e["id"]]}).json()
    assert s["meals"] == ["dessert"]
    imp = a.post("/api/meals/import", json={"name": "Cake", "meals": ["dessert"], "ingredients": [{"name": "flour"}]}).json()
    assert imp["meals"] == ["dessert"]


def test_default_meal_accepts_dessert(a, b):
    r = a.put("/api/settings", json={"default_meal": "dessert"})
    assert r.status_code == 200 and r.json()["default_meal"] == "dessert"
    assert a.get("/api/settings").json()["default_meal"] == "dessert"
    assert b.get("/api/settings").json()["default_meal"] is None
    assert a.put("/api/settings", json={"default_meal": "pudding"}).status_code == 400


def test_no_check_constraint_limits_meal_names(env):
    """Meals are validated in core.MEALS only; no table has a CHECK on meal, so existing databases need no rebuild."""
    with db.conn() as c:
        sql = " ".join(r[0] or "" for r in c.execute("SELECT sql FROM sqlite_master"))
    assert re.search(r"\bCHECK\s*\(", sql, re.I) is None


def test_older_database_accepts_dessert(tmp_path, monkeypatch, env):
    """A database made before dessert (same tables, rows using the four older meals) keeps its rows and takes dessert at once."""
    with db.conn() as c:
        c.execute("INSERT INTO foods(source,name,serving_amount,serving_unit,kcal,carbs,protein,fat,created_by) "
                  "VALUES('custom','Cake',1,'slice',300,40,4,14,1)")
        fid = c.execute("SELECT id FROM foods WHERE name='Cake'").fetchone()[0]
        c.execute("INSERT INTO entries(user_id,day,meal,food_id,name,amount,unit,servings,kcal,carbs,protein,fat) "
                  "VALUES(1,'2025-01-01','snack',?,'Cake',1,'slice',1,300,40,4,14)", (fid,))
        c.execute("INSERT INTO settings(user_id,default_meal) VALUES(1,'snack')")
        core.init(c)  # running init again over existing data is safe
    a = env["a"]
    assert a.get("/api/settings").json()["default_meal"] == "snack"
    assert a.put("/api/settings", json={"default_meal": "dessert"}).json()["default_meal"] == "dessert"
    e = a.post("/api/entries", json={"food_id": fid, "amount": 1, "unit": "slice", "meal": "dessert", "day": "2025-01-01"}).json()
    assert e["meal"] == "dessert"
    meals = [x["meal"] for x in a.get("/api/day", params={"day": "2025-01-01"}).json()["entries"]]
    assert sorted(meals) == ["dessert", "snack"]
    raw = sqlite3.connect(str(tmp_path / "t.db"))
    try:
        raw.execute("INSERT INTO favorite_tags(user_id,food_id,meal) VALUES(1,?,'dessert')", (fid,))
        raw.commit()
    finally:
        raw.close()
