"""Meal tags, auto-tagging, the Saved API and My foods."""
from app import core, db
from tests.test_core import BREAD, PB, SALT, a, b, env, food, log  # noqa: F401


def fav(client, f):
    assert client.post(f"/api/favorites/{f['id']}").status_code == 200


def tags(client, f):
    items = client.get("/api/quick/favorites").json()["items"]
    return next(i for i in items if i["food"]["id"] == f["id"])


def test_new_favorites_start_untagged_and_tags_validate(a, b):
    f = food(a)
    fav(a, f)
    assert tags(a, f)["meals"] == [] and tags(a, f)["counts"] == {}
    r = a.put(f"/api/favorites/{f['id']}/tags", json={"meals": ["snack", "lunch", "lunch"]})
    assert r.json()["meals"] == ["lunch", "snack"]
    assert tags(a, f)["meals"] == ["lunch", "snack"]
    for bad in ({"meals": ["brunch"]}, {"meals": "lunch"}, {}, {"meals": [None]}):
        assert a.put(f"/api/favorites/{f['id']}/tags", json=bad).status_code == 400
    assert b.put(f"/api/favorites/{f['id']}/tags", json={"meals": ["lunch"]}).status_code == 404
    assert a.put(f"/api/favorites/{f['id']}/tags", json={"meals": []}).json()["meals"] == []


def test_logging_a_favorite_with_a_meal_auto_tags_it_only(a):
    fb, other = food(a), food(a, PB)
    fav(a, fb)
    log(a, fb, meal="lunch")
    log(a, fb, meal="dinner")
    log(a, fb, meal="lunch")
    log(a, fb)  # no meal adds nothing
    log(a, other, meal="lunch")  # not a favorite
    item = tags(a, fb)
    assert item["meals"] == ["lunch", "dinner"] and item["counts"] == {"lunch": 2, "dinner": 1}
    fav(a, other)
    assert tags(a, other)["meals"] == []
    # tags are never removed by logging with another meal
    a.put(f"/api/favorites/{fb['id']}/tags", json={"meals": ["snack"]})
    log(a, fb, meal="lunch")
    assert tags(a, fb)["meals"] == ["lunch", "snack"]


def test_recipe_tags_patch_and_auto_tag(a, b):
    f = food(a)
    m = a.post("/api/meals", json={"name": "R", "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).json()
    assert m["meals"] == [] and m["counts"] == {}
    a.post(f"/api/meals/{m['id']}/log", json={"meal": "dinner"})
    a.post(f"/api/meals/{m['id']}/log", json={"meal": "dinner"})
    a.post(f"/api/meals/{m['id']}/log", json={})
    got = a.get("/api/meals").json()["meals"][0]
    assert got["meals"] == ["dinner"] and got["counts"] == {"dinner": 2}
    r = a.patch(f"/api/meals/{m['id']}", json={"meals": ["breakfast", "dinner"], "name": " New "}).json()
    assert r["meals"] == ["breakfast", "dinner"] and r["name"] == "New"
    assert a.patch(f"/api/meals/{m['id']}", json={"meals": ["x"]}).status_code == 400
    assert a.patch(f"/api/meals/{m['id']}", json={"name": " "}).status_code == 400
    assert a.patch(f"/api/meals/{m['id']}", json={}).status_code == 400
    assert b.patch(f"/api/meals/{m['id']}", json={"name": "Hack"}).status_code == 404
    assert a.delete(f"/api/meals/{m['id']}").status_code == 200
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM recipe_tags").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM recipe_logs").fetchone()[0] == 0


def test_recipe_items_edit_and_remove(a):
    f1, f2 = food(a), food(a, PB)
    m = a.post("/api/meals", json={"name": "R", "items": [{"food_id": f1["id"], "amount": 1, "unit": "slice"},
                                                           {"food_id": f2["id"], "amount": 2, "unit": "tbsp"}]}).json()
    r = a.patch(f"/api/meals/{m['id']}", json={"items": [{"food_id": f2["id"], "amount": 4, "unit": "tbsp"}]}).json()
    assert [(i["food_id"], i["amount"]) for i in r["items"]] == [(f2["id"], 4)]
    assert a.patch(f"/api/meals/{m['id']}", json={"items": []}).status_code == 400
    assert a.patch(f"/api/meals/{m['id']}", json={"items": [{"food_id": f2["id"], "amount": 1, "unit": "x" * 31}]}).status_code == 400
    assert len(a.get("/api/meals").json()["meals"][0]["items"]) == 1


def test_recipe_created_with_a_meal_is_tagged(a):
    f = food(a)
    m = a.post("/api/meals", json={"name": "R", "meal": "lunch", "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).json()
    assert m["meals"] == ["lunch"]


def test_recipe_created_with_several_meal_tags(a):
    f = food(a)
    item = {"food_id": f["id"], "amount": 2, "unit": "slice"}
    m = a.post("/api/meals", json={"name": "R", "meals": ["snack", "breakfast", "snack"], "items": [item]}).json()
    assert m["meals"] == ["breakfast", "snack"] and m["meal"] == "breakfast"
    assert a.get("/api/saved").json()["recipes"][0]["meals"] == ["breakfast", "snack"]
    assert a.post("/api/meals", json={"name": "R", "meals": [], "items": [item]}).json()["meals"] == []
    assert a.post("/api/meals", json={"name": "R", "meals": ["brunch"], "items": [item]}).status_code == 400
    assert a.post("/api/meals", json={"name": "R", "meals": "lunch", "items": [item]}).status_code == 400
    assert a.post("/api/meals", json={"name": "R", "meals": ["lunch"], "items": []}).status_code == 400


def test_recipe_from_scratch_keeps_micronutrients(a):
    f = a.post("/api/foods", json={**SALT, "sodium": 600, "potassium": 100}).json()
    m = a.post("/api/meals", json={"name": "Salty", "meals": ["dinner"], "items": [{"food_id": f["id"], "amount": 200, "unit": "g"}]}).json()
    item = m["items"][0]
    assert item["servings"] == 2 and item["sodium"] == 1200 and item["potassium"] == 200
    entries = a.post(f"/api/meals/{m['id']}/log", json={"meal": "dinner"}).json()["entries"]
    assert entries[0]["sodium"] == 1200


def test_remove_from_my_lists_hides_but_keeps_history(a, b):
    f = food(a)
    fav(a, f)
    fav(b, f)
    a.put(f"/api/favorites/{f['id']}/tags", json={"meals": ["lunch"]})
    log(a, f, meal="lunch", day="2020-01-02")
    log(b, f, day="2020-01-02")
    assert a.post(f"/api/saved/favorites/{f['id']}/remove").json()["removed"] is True
    assert a.get("/api/quick/favorites").json()["items"] == []
    assert a.get("/api/quick/recent").json()["items"] == []
    assert a.get("/api/quick/yesterday", params={"day": "2020-01-03"}).json()["items"] == []
    assert len(a.get("/api/day", params={"day": "2020-01-02"}).json()["entries"]) == 1
    assert len(b.get("/api/quick/recent").json()["items"]) == 1 and len(b.get("/api/quick/favorites").json()["items"]) == 1
    assert [x["id"] for x in a.get("/api/foods/search", params={"q": "bread", "remote": 0}).json()["results"]] == [f["id"]]
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM favorite_tags WHERE user_id=1").fetchone()[0] == 0
    assert a.post(f"/api/saved/favorites/{f['id']}/remove").status_code == 404  # no longer a favorite
    fav(a, f)  # favoriting again un-hides and starts untagged
    assert len(a.get("/api/quick/recent").json()["items"]) == 1 and tags(a, f)["meals"] == []


def test_logging_unhides(a):
    f = food(a)
    fav(a, f)
    a.post(f"/api/saved/favorites/{f['id']}/remove")
    assert a.get("/api/quick/recent").json()["items"] == []
    log(a, f)
    assert len(a.get("/api/quick/recent").json()["items"]) == 1


def test_saved_lists_only_own_items(a, b):
    f, mine = food(a), food(a, SALT)
    other = food(b, PB)
    fav(a, f)
    fav(b, other)
    a.post("/api/meals", json={"name": "R", "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]})
    s = a.get("/api/saved").json()
    assert [x["food"]["id"] for x in s["favorites"]] == [f["id"]]
    assert [m["name"] for m in s["recipes"]] == ["R"]
    assert {x["id"] for x in s["foods"]} == {f["id"], mine["id"]} and {x["id"]: x["in_use"] for x in s["foods"]} == {f["id"]: True, mine["id"]: False}
    assert [x["id"] for x in b.get("/api/saved").json()["foods"]] == [other["id"]]


def test_my_foods_edit_rules(a, b):
    f = food(a, SALT)
    r = a.patch(f"/api/foods/{f['id']}", json={"name": "Salt", "kcal": 5, "serving_unit": "g", "serving_amount": 10})
    assert r.status_code == 200 and r.json()["name"] == "Salt" and r.json()["kcal"] == 5 and r.json()["serving_amount"] == 10
    assert a.patch(f"/api/foods/{f['id']}", json={"kcal": -1}).status_code == 400
    assert a.patch(f"/api/foods/{f['id']}", json={}).status_code == 400
    assert b.patch(f"/api/foods/{f['id']}", json={"name": "x"}).status_code == 403
    e = log(a, f, amount=10)
    assert a.get("/api/saved").json()["foods"][0]["in_use"] is True
    r = a.patch(f"/api/foods/{f['id']}", json={"kcal": 50})
    assert r.status_code == 409 and "rename" in r.json()["detail"]
    assert a.patch(f"/api/foods/{f['id']}", json={"name": "Sea salt", "kcal": 5}).json()["name"] == "Sea salt"
    day = a.get("/api/day", params={"day": e["day"]}).json()["entries"][0]
    assert day["name"] == "Salt" and day["kcal"] == e["kcal"]  # past entries keep their snapshot
    assert a.patch("/api/foods/9999", json={"name": "x"}).status_code == 404


def test_my_foods_delete_is_soft_and_never_blocked(a, b):
    f, used, shared = food(a, SALT), food(a), food(a, PB)
    assert a.delete(f"/api/foods/{f['id']}").json() == {"deleted": f["id"], "everyone": True}
    assert f["id"] not in [x["id"] for x in a.get("/api/saved").json()["foods"]]
    log(a, used)
    assert a.delete(f"/api/foods/{used['id']}").status_code == 200  # no 409 for a food in a log
    m = a.post("/api/meals", json={"name": "R", "items": [{"food_id": shared["id"], "amount": 1, "unit": "tbsp"}]}).json()
    assert a.delete(f"/api/foods/{shared['id']}").status_code == 200  # nor for one in a recipe
    assert a.get(f"/api/meals/{m['id']}").json()["items"][0]["food"]["name"] == shared["name"]
    assert a.delete("/api/foods/9999").status_code == 404


def test_foods_not_created_by_the_user_are_not_editable(a):
    with db.conn() as c:
        c.execute("INSERT INTO foods(source, source_id, name, serving_amount, serving_unit, kcal, carbs, protein, fat) "
                  "VALUES('fdc','1','Rice',1,'cup',1,1,1,1)")
        c.execute("INSERT INTO foods(source, name, serving_amount, serving_unit, kcal, carbs, protein, fat) "
                  "VALUES('custom','Old',1,'cup',1,1,1,1)")
    assert a.get("/api/saved").json()["foods"] == []
    assert a.patch("/api/foods/1", json={"name": "x"}).status_code == 403
    assert a.patch("/api/foods/2", json={"name": "x"}).status_code == 403


def test_init_migrates_an_old_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        c.execute("CREATE TABLE foods(id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT, name TEXT NOT NULL, "
                  "brand TEXT, serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL, serving_g REAL, serving_ml REAL, "
                  "label_text TEXT NOT NULL DEFAULT '', kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, "
                  "fat REAL NOT NULL, fiber REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, source_id))")
        c.execute("INSERT INTO foods(source,name,serving_amount,serving_unit,kcal,carbs,protein,fat) VALUES('custom','X',1,'g',1,1,1,1)")
        core.init(c)
        core.init(c)  # running twice is safe
        assert c.execute("SELECT created_by FROM foods").fetchone()[0] is None
        assert c.execute("SELECT COUNT(*) FROM favorite_tags").fetchone()[0] == 0
