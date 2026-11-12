"""A logged recipe is one item on Today (a recipe log group), while every ingredient row stays an entry so totals are exact."""
import sqlite3

import pytest

from app import core, db
from tests.test_core import BREAD, PB, a, b, env, food, log  # noqa: F401  (fixtures)

DAY = "2025-06-02"


def recipe(client, items, servings=None, yld=None, name="Toast"):
    m = client.post("/api/meals", json={"name": name, "items": items}).json()
    if servings or yld:
        m = client.patch(f"/api/meals/{m['id']}", json={"servings": servings, "yield": yld}).json()
    return m


def toast(client, servings=2):
    bread, pb = food(client, {**BREAD, "sodium": 170}), food(client, PB)
    return recipe(client, [{"food_id": bread["id"], "amount": 2, "unit": "slice"},
                           {"food_id": pb["id"], "amount": 32, "unit": "g"}], servings=servings), bread, pb


def day(client, d=DAY):
    return client.get("/api/day", params={"day": d}).json()


def test_logged_recipe_is_one_item_with_the_same_totals(a):
    m, bread, pb = toast(a)
    r = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "meal": "lunch", "amount": 1, "unit": "serving"})
    assert r.status_code == 200, r.text
    assert len(r.json()["entries"]) == 2 and r.json()["group"]["kind"] == "recipe"
    d = day(a)
    assert len(d["entries"]) == 1
    g = d["entries"][0]
    assert (g["kind"], g["name"], g["amount"], g["unit"], g["meal"], g["source"], g["id"]) == ("recipe", "Toast", 1, "serving", "lunch", None, None)
    assert [p["name"] for p in g["parts"]] == ["Bread", "Peanut Butter"] and all(p["kind"] == "food" for p in g["parts"])
    assert all(p["group_id"] == g["group_id"] and p["meal"] == "lunch" for p in g["parts"])
    for k in ("kcal", "carbs", "protein", "fat", "fiber"):
        assert g[k] == pytest.approx(sum(p[k] for p in g["parts"]))
        assert d["totals"][k] == pytest.approx(round(g[k], 1))
    assert g["sodium"] == 170 and g["calcium"] is None  # known parts only; null when no part knows it
    # the same rows logged one by one give the very same totals, micros and goals
    log(a, bread, 1, "slice", day="2025-06-03", meal="lunch")
    log(a, pb, 16, "g", day="2025-06-03", meal="lunch")
    plain = day(a, "2025-06-03")
    for key in ("totals", "percent", "remaining", "micros"):
        assert plain[key] == d[key], key
    assert d["micros"]["sodium"]["count"] == 2  # every ingredient row still counts as one food


def test_change_portion_rescales_every_row(a):
    m, *_ = toast(a)
    gid = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "amount": 1, "unit": "serving"}).json()["group"]["group_id"]
    one = day(a)["entries"][0]
    r = a.patch(f"/api/entry-groups/{gid}", json={"amount": 2, "unit": "serving"})
    assert r.status_code == 200, r.text
    two = day(a)["entries"][0]
    assert (two["amount"], two["unit"]) == (2, "serving")
    assert [p["amount"] for p in two["parts"]] == [2, 32]
    assert two["kcal"] == pytest.approx(2 * one["kcal"]) and day(a)["totals"]["kcal"] == pytest.approx(round(two["kcal"], 1))
    pct = a.patch(f"/api/entry-groups/{gid}", json={"amount": 25, "unit": "pct"}).json()
    assert (pct["amount"], pct["unit"]) == (25, "pct") and [p["amount"] for p in pct["parts"]] == [0.5, 8]
    assert a.patch(f"/api/entry-groups/{gid}", json={"amount": 1, "unit": "g"}).status_code == 400  # no yield set
    assert a.patch(f"/api/entry-groups/{gid}", json={"amount": 0, "unit": "serving"}).status_code == 400
    assert a.patch(f"/api/entry-groups/{gid}", json={"amount": 500, "unit": "serving"}).status_code == 400
    assert a.patch(f"/api/entry-groups/{gid}", json={}).status_code == 400


def test_yield_units_and_whole_recipe(a):
    bread = food(a)
    m = recipe(a, [{"food_id": bread["id"], "amount": 4, "unit": "slice"}], servings=4, yld={"amount": 400, "unit": "g"})
    g = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "amount": 100, "unit": "g"}).json()["group"]
    assert (g["amount"], g["unit"], g["kcal"]) == (100, "g", 90) and g["parts"][0]["amount"] == 1
    assert [p["unit"] for p in g["portions"]][:3] == ["serving", "pct", "g"]
    g = a.patch(f"/api/entry-groups/{g['group_id']}", json={"amount": 2, "unit": "serving"}).json()
    assert g["kcal"] == 180 and g["parts"][0]["amount"] == 2
    whole = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY}).json()["group"]  # no amount: the whole recipe
    assert (whole["amount"], whole["unit"], whole["kcal"]) == (4, "serving", 360)
    # the portions are kept with the log, so it still rescales after the recipe is deleted
    a.delete(f"/api/meals/{m['id']}")
    assert a.patch(f"/api/entry-groups/{g['group_id']}", json={"amount": 200, "unit": "g"}).json()["kcal"] == 180


def test_change_meal_moves_the_whole_group(a):
    m, bread, _ = toast(a)
    gid = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "meal": "lunch"}).json()["group"]["group_id"]
    log(a, bread, day=DAY, meal="lunch")
    g = a.patch(f"/api/entry-groups/{gid}", json={"meal": "dinner"}).json()
    assert g["meal"] == "dinner" and {p["meal"] for p in g["parts"]} == {"dinner"}
    assert [(e["kind"], e["meal"]) for e in day(a)["entries"]] == [("recipe", "dinner"), ("food", "lunch")]
    assert a.patch(f"/api/entry-groups/{gid}", json={"meal": None}).json()["meal"] is None
    assert a.patch(f"/api/entry-groups/{gid}", json={"meal": "brunch"}).status_code == 400


def test_delete_removes_the_whole_group_and_only_mine(a, b):
    m, bread, _ = toast(a)
    gid = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY}).json()["group"]["group_id"]
    e = log(a, bread, day=DAY)
    for call in (b.get, b.delete):
        assert call(f"/api/entry-groups/{gid}").status_code == 404
    assert b.patch(f"/api/entry-groups/{gid}", json={"meal": "lunch"}).status_code == 404
    assert a.get(f"/api/entry-groups/{gid}").json()["group_id"] == gid
    assert a.delete(f"/api/entry-groups/{gid}").json() == {"deleted": gid}
    d = day(a)
    assert [x["id"] for x in d["entries"]] == [e["id"]] and d["totals"]["kcal"] == e["kcal"]
    assert a.get(f"/api/entry-groups/{gid}").status_code == 404
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM entries WHERE group_id=?", (gid,)).fetchone()[0] == 0


def test_single_rows_of_a_group(a):
    m, *_ = toast(a)
    g = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "meal": "lunch"}).json()["group"]
    first, second = g["parts"]
    # moving one row to another meal takes it out of the group; deleting the last row drops the group
    moved = a.patch(f"/api/entries/{first['id']}", json={"meal": "snack"}).json()
    assert moved["group_id"] is None
    kinds = [(e["kind"], e["meal"]) for e in day(a)["entries"]]
    assert kinds == [("food", "snack"), ("recipe", "lunch")]
    assert a.delete(f"/api/entries/{second['id']}").status_code == 200
    assert a.get(f"/api/entry-groups/{g['group_id']}").status_code == 404
    assert [e["kind"] for e in day(a)["entries"]] == ["food"]


def test_legacy_recipe_entries_stay_separate(a):
    m, bread, pb = toast(a)
    a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "meal": "lunch"})
    with db.conn() as c:  # what a recipe log looked like before groups: plain rows, nothing links them
        c.execute("UPDATE entries SET group_id=NULL")
        c.execute("DELETE FROM entry_groups")
    d = day(a)
    assert [(e["kind"], e["name"]) for e in d["entries"]] == [("food", "Bread"), ("food", "Peanut Butter")]


def test_yesterday_lists_a_recipe_log_once_and_copies_it_as_one_group(a):
    m, bread, _ = toast(a)
    log(a, bread, day=DAY, meal="breakfast")
    a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "meal": "lunch", "amount": 1, "unit": "serving"})
    items = a.get("/api/quick/yesterday", params={"day": "2025-06-03"}).json()["items"]
    assert [it.get("kind", "food") for it in items] == ["food", "recipe"]
    rec = items[1]
    assert (rec["name"], rec["amount"], rec["unit"], rec["meal"], rec["parts"]) == ("Toast", 1, "serving", "lunch", 2)
    before = a.get(f"/api/meals/{m['id']}").json()["counts"]
    r = a.post(f"/api/entry-groups/{rec['group_id']}/copy", json={"day": "2025-06-03", "meal": "dinner"})
    assert r.status_code == 200, r.text
    d = day(a, "2025-06-03")
    assert [(e["kind"], e["meal"], e["name"]) for e in d["entries"]] == [("recipe", "dinner", "Toast")]
    assert d["entries"][0]["kcal"] == rec["kcal"] and len(d["entries"][0]["parts"]) == 2
    assert a.get(f"/api/meals/{m['id']}").json()["counts"] == {**before, "dinner": before.get("dinner", 0) + 1}
    half = a.post(f"/api/entry-groups/{rec['group_id']}/copy", json={"day": "2025-06-04", "amount": 0.5, "unit": "serving"}).json()
    assert half["meal"] == "lunch" and half["kcal"] == pytest.approx(rec["kcal"] / 2, abs=0.02)


def test_save_as_recipe_uses_the_ingredient_rows(a):
    m, bread, pb = toast(a)
    g = a.post(f"/api/meals/{m['id']}/log", json={"day": DAY, "meal": "lunch"}).json()["group"]
    e = log(a, bread, day=DAY, meal="lunch")
    ids = [p["id"] for p in g["parts"]] + [e["id"]]
    r = a.post("/api/meals/from-meal", json={"name": "Lunch", "day": DAY, "meal": "lunch", "entry_ids": ids})
    assert r.status_code == 200, r.text
    assert [(i["food"]["name"], i["amount"]) for i in r.json()["items"]] == [("Bread", 2), ("Peanut Butter", 32), ("Bread", 1)]


def test_migration_adds_the_link_to_an_older_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        c.executescript("""
            CREATE TABLE entries(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, meal TEXT, food_id INTEGER,
              name TEXT NOT NULL, brand TEXT, amount REAL NOT NULL, unit TEXT NOT NULL, servings REAL NOT NULL,
              kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL, created_at TEXT);
            CREATE TABLE recipe_logs(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL, meal TEXT NOT NULL);
            INSERT INTO entries(user_id, day, meal, name, amount, unit, servings, kcal, carbs, protein, fat)
              VALUES (1, '2025-06-02', 'lunch', 'Old bread', 1, 'slice', 1, 90, 17, 4, 1.5);
            INSERT INTO recipe_logs(meal_id, meal) VALUES (7, 'lunch');""")
    for _ in range(2):  # safe to run twice
        with db.conn() as c:
            core.init(c)
    with db.conn() as c:
        assert "group_id" in {r[1] for r in c.execute("PRAGMA table_info(entries)")}
        assert c.execute("SELECT group_id FROM entries").fetchone()[0] is None
        assert c.execute("SELECT COUNT(*) FROM recipe_logs").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM entry_groups").fetchone()[0] == 0
        rows = c.execute("SELECT e.*, NULL AS source FROM entries e").fetchall()
        items = core.day_items(c, 1, rows)
    assert [(i["kind"], i["name"], i["group_id"]) for i in items] == [("food", "Old bread", None)]
