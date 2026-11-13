"""Recipe total yield, logging a part of a recipe (servings, percent, yield units) and the bulk row update."""
import pytest

from app import core, db
from tests.test_core import BREAD, PB, a, b, env, food  # noqa: F401
from tests.test_recipe_match import imported


def made(client):
    """A complete recipe: 2 slices of bread (68 g) and 2 tbsp peanut butter (32 g), making 2 servings."""
    bread, pb = food(client, BREAD), food(client, PB)
    m = client.post("/api/meals", json={"name": "PB Toast", "items": [
        {"food_id": bread["id"], "amount": 2, "unit": "slice"}, {"food_id": pb["id"], "amount": 2, "unit": "tbsp"}]}).json()
    return client.patch(f"/api/meals/{m['id']}", json={"servings": 2}).json()


def test_new_recipes_have_no_yield_and_two_portion_units(a):
    m = made(a)
    assert m["yield"] is None
    assert [(p["unit"], p["whole"]) for p in m["portions"]] == [("serving", 2), ("pct", 100)]
    assert m["ingredient_grams"] == 100.0  # 68 g of bread + 32 g of peanut butter, every weight exact


def test_set_and_clear_yield(a, b):
    m = made(a)
    url = f"/api/meals/{m['id']}"
    r = a.patch(url, json={"yield": {"amount": 1.2, "unit": "kg"}}).json()
    assert r["yield"] == {"amount": 1.2, "unit": "kg"}
    units = {p["unit"]: p["whole"] for p in r["portions"]}
    assert list(units)[:3] == ["serving", "pct", "kg"] and units["g"] == 1200 and set(units) == {"serving", "pct", "kg", "g", "oz", "lb"}
    assert units["oz"] == pytest.approx(1200 / 28.3495, rel=1e-6)
    r = a.patch(url, json={"yield": {"amount": 6, "unit": "cups"}}).json()
    assert r["yield"] == {"amount": 6, "unit": "cup"} and "ml" in {p["unit"] for p in r["portions"]} and "g" not in {p["unit"] for p in r["portions"]}
    assert a.patch(url, json={"yield": None}).json()["yield"] is None
    assert b.patch(url, json={"yield": {"amount": 1, "unit": "g"}}).status_code == 404


@pytest.mark.parametrize("y", [{"amount": 0, "unit": "g"}, {"amount": -1, "unit": "g"}, {"amount": 5, "unit": "slice"},
                               {"amount": 5}, {"unit": "g"}, {"amount": "x", "unit": "g"}, {"amount": 2_000_000, "unit": "g"},
                               {"amount": 5, "unit": "g", "evil": 1}, "500 g", [500, "g"]])
def test_yield_validation(a, y):
    m = made(a)
    assert a.patch(f"/api/meals/{m['id']}", json={"yield": y}).status_code == 400


def kcal_of(entries):
    return round(sum(e["kcal"] for e in entries), 2)


def test_log_part_of_a_recipe(a):
    m = made(a)  # 2 * 90 + 190 = 370 kcal in all, 2 servings
    url = f"/api/meals/{m['id']}/log"
    assert kcal_of(a.post(url, json={}).json()["entries"]) == 370  # no amount: the whole saved recipe, as before
    assert kcal_of(a.post(url, json={"amount": 1, "unit": "serving"}).json()["entries"]) == 185
    assert kcal_of(a.post(url, json={"amount": 25, "unit": "pct"}).json()["entries"]) == 92.5
    a.patch(f"/api/meals/{m['id']}", json={"yield": {"amount": 400, "unit": "g"}})
    r = a.post(url, json={"amount": 100, "unit": "g", "meal": "lunch"}).json()["entries"]
    assert kcal_of(r) == 92.5 and [e["amount"] for e in r] == [0.5, 0.5] and r[0]["meal"] == "lunch"
    assert kcal_of(a.post(url, json={"amount": 0.5, "unit": "lb"}).json()["entries"]) == pytest.approx(370 * 453.592 * 0.5 / 400, abs=0.05)
    # items from the checklist still win over amount
    items = [{"food_id": i["food_id"], "amount": 1, "unit": "slice"} for i in m["items"][:1]]
    assert kcal_of(a.post(url, json={"items": items, "amount": 3, "unit": "serving"}).json()["entries"]) == 90


@pytest.mark.parametrize("body", [{"amount": 1, "unit": "cup"}, {"amount": 0, "unit": "serving"}, {"amount": -2, "unit": "pct"},
                                  {"amount": "x", "unit": "serving"}, {"unit": "serving"}, {"amount": 1},
                                  {"amount": 201, "unit": "serving"}, {"amount": 10001, "unit": "pct"}])
def test_log_amount_validation(a, body):
    m = made(a)
    assert a.post(f"/api/meals/{m['id']}/log", json=body).status_code == 400


def test_ingredient_grams_needs_exact_weights_and_a_complete_recipe(a):
    m = imported(a)
    assert m["ingredient_grams"] is None
    bread = food(a, BREAD)
    salt = food(a, {"name": "Salt", "serving_amount": 1, "serving_unit": "tsp", "kcal": 0, "carbs": 0, "protein": 0, "fat": 0})
    url = f"/api/meals/{m['id']}/items"
    ids = [i["id"] for i in m["items"]]
    r = a.patch(url, json={"items": [{"id": ids[0], "food_id": bread["id"], "amount": 2, "unit": "slice"}, {"id": ids[1], "skipped": True},
                                     {"id": ids[2], "food_id": salt["id"], "amount": 1, "unit": "tsp"}]}).json()
    assert r["complete"] and r["ingredient_grams"] is None  # salt is known only by volume
    r = a.patch(url, json={"items": [{"id": ids[2], "skipped": True}]}).json()
    assert r["ingredient_grams"] == 68.0


def test_bulk_rows_skip_all_and_restore(a, b):
    m = imported(a)
    bread = food(a, BREAD)
    url = f"/api/meals/{m['id']}/items"
    ids = [i["id"] for i in m["items"]]
    before = a.patch(url, json={"items": [{"id": ids[0], "food_id": bread["id"], "amount": 2, "unit": "slice"}]}).json()
    r = a.patch(url, json={"items": [{"id": i, "skipped": True} for i in ids[1:]]}).json()
    assert (r["matched"], r["skipped"], r["complete"]) == (1, 2, True)
    # writing the last saved state back (Back on Match Ingredients), including a matched row that was skipped
    back = [{"id": i["id"], "food_id": i["food_id"], "skipped": i["skipped"],
             **({"amount": i["amount"], "unit": i["unit"], "check": i["check"]} if i["food_id"] else {})} for i in before["items"]]
    back[0]["skipped"] = True
    r = a.patch(url, json={"items": back}).json()
    assert [(i["food_id"], i["skipped"]) for i in r["items"]] == [(bread["id"], True), (None, False), (None, False)]
    assert b.patch(url, json={"items": [{"id": ids[0], "skipped": False}]}).status_code == 404
    assert a.patch(url, json={"items": [{"id": 999, "skipped": False}]}).status_code == 404


@pytest.mark.parametrize("items", [[], "x", [{"skipped": True}], [{"id": 1}], [{"id": "a", "skipped": True}],
                                   [{"id": 1, "skipped": "yes"}], [{"id": 1, "amount": 2}], [{"id": 1, "evil": 1}]])
def test_bulk_rows_validation(a, items):
    m = imported(a)
    if items and isinstance(items, list) and items[0].get("id") == 1:
        items = [{**items[0], "id": m["items"][0]["id"]}]
    assert a.patch(f"/api/meals/{m['id']}/items", json={"items": items}).status_code == 400


def test_bulk_rows_are_all_or_nothing(a):
    m = imported(a)
    bread = food(a, BREAD)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}/items"
    r = a.patch(url, json={"items": [{"id": ids[0], "skipped": True}, {"id": ids[1], "food_id": bread["id"], "amount": 2, "unit": "can" * 11}]})
    assert r.status_code == 400 and "row 2" in r.json()["detail"]
    assert a.get(f"/api/meals/{m['id']}").json()["skipped"] == 0
    assert a.patch(url, json={"items": [{"id": ids[0], "skipped": True}, {"id": ids[0], "skipped": False}]}).status_code == 400


def test_old_databases_get_the_yield_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old3.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.executescript("""
        CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT, meal TEXT, servings REAL, steps TEXT);
        INSERT INTO users(id, username) VALUES (1, 'a');
        INSERT INTO meals(id, user_id, name, servings) VALUES (3, 1, 'Soup', 4);
        """)
    for _ in range(2):
        with db.conn() as c:
            core.init(c)
    with db.conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(meals)")}
        assert {"yield_amount", "yield_unit"} <= cols
        m = core.meal_dict(c, c.execute("SELECT * FROM meals WHERE id=3").fetchone())
        assert m["yield"] is None and m["servings"] == 4 and [p["unit"] for p in m["portions"]] == ["serving", "pct"]
        c.execute("UPDATE meals SET yield_amount=500, yield_unit='bogus' WHERE id=3")  # an unknown unit reads as no yield
        assert core.meal_dict(c, c.execute("SELECT * FROM meals WHERE id=3").fetchone())["yield"] is None
