"""Shared recipes (#18) and the Recipes owner filter (#25): every permission path is checked on the server.
a (id 1) owns the recipes, b (id 2) is another user, admin (id 3) is an admin. Private is the default."""
import sqlite3
from datetime import date

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import core, db, deps, lookup, recipe_ai
from tests.test_core import BREAD, PB

TODAY = date.today().isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        c.execute("INSERT INTO users(id, username, display_name, is_admin) VALUES (1, 'ann', 'Ann', 0), (2, 'bob', '', 0), (3, 'root', 'Root', 1)")

    async def nothing(*a, **k):
        return []

    monkeypatch.setattr(lookup, "search", nothing)
    monkeypatch.setattr(lookup, "search_off", nothing)
    api = FastAPI()
    api.include_router(core.router)
    api.include_router(recipe_ai.router)

    def fake_user(request: Request):
        uid = int(request.headers["x-user"])
        return {"id": uid, "username": "u", "display_name": "U", "is_admin": uid == 3}

    api.dependency_overrides[deps.current_user] = fake_user
    return {k: TestClient(api, headers={"x-user": str(i)}) for k, i in (("a", 1), ("b", 2), ("admin", 3))}


def food(client, data):
    r = client.post("/api/foods", json=data)
    assert r.status_code == 200, r.text
    return r.json()


def recipe(env, shared=False):
    """a's recipe: one of a's own custom foods (Bread, 1 slice), plus an unmatched line."""
    a = env["a"]
    f = food(a, BREAD)
    m = a.post("/api/meals", json={"name": "Toast", "meals": ["breakfast"], "steps": ["Toast it"],
                                   "items": [{"food_id": f["id"], "amount": 2, "unit": "slice"}]}).json()
    a.post(f"/api/meals/{m['id']}/items", json={"src": {"name": "butter", "text": "butter to taste"}})
    if shared:
        assert a.patch(f"/api/meals/{m['id']}", json={"shared": True}).json()["shared"] is True
    return m, f


def ids(client, owner=None):
    r = client.get("/api/meals", params={"owner": owner} if owner else None)
    assert r.status_code == 200, r.text
    return [m["id"] for m in r.json()["meals"]]


def test_migration_keeps_old_recipes_private_and_adds_columns(tmp_path):
    c = sqlite3.connect(tmp_path / "old.db")
    c.row_factory = sqlite3.Row
    c.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, display_name TEXT);"
        "CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT, meal TEXT);"
        "CREATE TABLE recipe_logs(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL, meal TEXT NOT NULL);"
        "CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT);"
        "INSERT INTO meals(id, user_id, name) VALUES(7, 1, 'Old');"
        "INSERT INTO recipe_logs(meal_id, meal) VALUES(7, 'lunch');"
        "INSERT INTO settings(user_id) VALUES(1);")
    core.init(c)
    core.init(c)  # safe to run twice
    assert c.execute("SELECT name, shared FROM meals WHERE id=7").fetchone()[:] == ("Old", 0)
    assert c.execute("SELECT meal, user_id FROM recipe_logs").fetchone()[:] == ("lunch", None)
    assert core.read_display(c, 1)["recipe_owner"] == "mine"


def test_private_by_default_and_invisible_to_others(env):
    a, b, admin = env["a"], env["b"], env["admin"]
    m, _ = recipe(env)
    assert m["shared"] is False and m["mine"] is True and m["can_edit"] is True and m["owner"] == {"id": 1, "name": "Ann"}
    for client in (b, admin):  # admins do not see private recipes either
        assert ids(client, "all") == [] and ids(client, "shared") == []
        assert client.get(f"/api/meals/{m['id']}").status_code == 404
        assert client.post(f"/api/meals/{m['id']}/log", json={}).status_code == 404
        assert client.post(f"/api/meals/{m['id']}/duplicate").status_code == 404
        assert client.patch(f"/api/meals/{m['id']}", json={"shared": True}).status_code == 404
        assert client.delete(f"/api/meals/{m['id']}").status_code == 404
        assert client.post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [m["items"][0]["id"]]}).status_code == 404
    assert ids(a) == [m["id"]] and ids(a, "shared") == []


def test_owner_filter_lists_mine_shared_and_all(env):
    a, b = env["a"], env["b"]
    m, _ = recipe(env, shared=True)
    mine_b = b.post("/api/meals/import", json={"name": "Bob Soup", "ingredients": [{"name": "water"}]}).json()
    assert ids(b) == [mine_b["id"]]  # the default is mine, as before
    assert ids(b, "mine") == [mine_b["id"]]
    assert ids(b, "shared") == [m["id"]]
    assert set(ids(b, "all")) == {m["id"], mine_b["id"]}
    assert ids(a, "shared") == []  # b's recipe is private
    assert b.get("/api/meals", params={"owner": "everyone"}).status_code == 400
    seen = next(x for x in b.get("/api/meals", params={"owner": "all"}).json()["meals"] if x["id"] == m["id"])
    assert seen["mine"] is False and seen["can_edit"] is False and seen["shared"] is True and seen["owner"]["name"] == "Ann"
    bob = next(x for x in a.get("/api/meals", params={"owner": "all"}).json()["meals"] if x["id"] == m["id"])
    assert bob["owner"]["name"] == "Ann"
    b.patch(f"/api/meals/{mine_b['id']}", json={"shared": True})
    assert next(x for x in a.get("/api/meals", params={"owner": "shared"}).json()["meals"])["owner"]["name"] == "bob"  # no display name


def test_others_can_read_and_log_a_shared_recipe_with_the_owners_custom_food(env):
    a, b = env["a"], env["b"]
    m, f = recipe(env, shared=True)
    got = b.get(f"/api/meals/{m['id']}")
    assert got.status_code == 200 and got.json()["items"][0]["food"]["name"] == "Bread"
    r = b.post(f"/api/meals/{m['id']}/log", json={"meal": "lunch", "amount": 1, "unit": "serving"})
    assert r.status_code == 200, r.text
    e = r.json()["entries"]
    assert len(e) == 1 and e[0]["food_id"] == f["id"] and e[0]["amount"] == 2
    assert e[0]["kcal"] == round(2 * BREAD["kcal"], 2)  # nutrition resolves from a's custom food
    day = b.get("/api/day", params={"day": TODAY}).json()
    assert day["totals"]["kcal"] == round(2 * BREAD["kcal"], 2)
    assert a.get("/api/day", params={"day": TODAY}).json()["entries"] == []  # nothing lands in a's day
    # b's log never tags a's recipe; counts are each viewer's own
    after = a.get(f"/api/meals/{m['id']}").json()
    assert after["meals"] == ["breakfast"] and after["counts"] == {}
    assert b.get(f"/api/meals/{m['id']}").json()["counts"] == {"lunch": 1}
    a.post(f"/api/meals/{m['id']}/log", json={"meal": "dinner"})
    assert a.get(f"/api/meals/{m['id']}").json()["counts"] == {"dinner": 1}
    assert a.get(f"/api/meals/{m['id']}").json()["meals"] == ["breakfast", "dinner"]
    # logging it again from Yesterday-like copy counts for b, still no tag on a's recipe
    gid = r.json()["group"]["group_id"]
    assert b.post(f"/api/entry-groups/{gid}/copy", json={"meal": "snack"}).status_code == 200
    assert b.get(f"/api/meals/{m['id']}").json()["counts"] == {"lunch": 1, "snack": 1}
    assert a.get(f"/api/meals/{m['id']}").json()["meals"] == ["breakfast", "dinner"]


def test_logging_a_shared_recipe_does_not_revive_the_owners_deleted_food(env):
    a, b = env["a"], env["b"]
    m, f = recipe(env, shared=True)
    assert a.delete(f"/api/foods/{f['id']}").json()["everyone"] is True  # only a's own recipe uses it
    assert b.post(f"/api/meals/{m['id']}/log", json={}).status_code == 200
    with db.conn() as c:
        assert c.execute("SELECT deleted FROM foods WHERE id=?", (f["id"],)).fetchone()[0] == 1
    assert a.get("/api/saved").json()["foods"] == []
    assert b.get(f"/api/meals/{m['id']}").json()["items"][0]["food"]["kcal"] == BREAD["kcal"]


def test_others_cannot_change_a_shared_recipe(env):
    a, b = env["a"], env["b"]
    m, f = recipe(env, shared=True)
    item = m["items"][0]["id"]
    p = food(b, PB)
    calls = [
        ("patch", f"/api/meals/{m['id']}", {"name": "Mine now"}),
        ("patch", f"/api/meals/{m['id']}", {"shared": False}),
        ("patch", f"/api/meals/{m['id']}", {"meals": ["lunch"]}),
        ("patch", f"/api/meals/{m['id']}", {"servings": 4}),
        ("patch", f"/api/meals/{m['id']}", {"steps": ["x"]}),
        ("patch", f"/api/meals/{m['id']}", {"items": [{"food_id": p["id"], "amount": 1, "unit": "tbsp"}]}),
        ("patch", f"/api/meals/{m['id']}/items/{item}", {"skipped": True}),
        ("patch", f"/api/meals/{m['id']}/items", {"items": [{"id": item, "skipped": True}]}),
        ("post", f"/api/meals/{m['id']}/items", {"src": {"name": "jam"}}),
        ("delete", f"/api/meals/{m['id']}/items/{item}", None),
        ("delete", f"/api/meals/{m['id']}/uncounted", None),
        ("delete", f"/api/meals/{m['id']}", None),
        ("post", f"/api/recipes/{m['id']}/match-search", {"item_ids": [item]}),
        ("post", f"/api/recipes/{m['id']}/match", {"item_ids": [item]}),
    ]
    for verb, path, body in calls:
        r = getattr(b, verb)(path, json=body) if body is not None else getattr(b, verb)(path)
        assert r.status_code == 403, (verb, path, r.status_code, r.text)
    same = a.get(f"/api/meals/{m['id']}").json()
    assert same["name"] == "Toast" and same["shared"] is True and len(same["items"]) == 2 and same["servings"] == 1


def test_owner_and_admin_can_change_and_unshare(env):
    a, admin, b = env["a"], env["admin"], env["b"]
    m, _ = recipe(env, shared=True)
    assert a.patch(f"/api/meals/{m['id']}", json={"shared": "yes"}).status_code == 400
    r = admin.get(f"/api/meals/{m['id']}").json()
    assert r["can_edit"] is True and r["mine"] is False
    assert admin.patch(f"/api/meals/{m['id']}", json={"name": "Toast Plus"}).json()["name"] == "Toast Plus"
    assert admin.patch(f"/api/meals/{m['id']}", json={"shared": False}).json()["shared"] is False
    with db.conn() as c:
        assert c.execute("SELECT user_id FROM meals WHERE id=?", (m["id"],)).fetchone()[0] == 1  # still a's
    assert b.get(f"/api/meals/{m['id']}").status_code == 404  # private again
    assert admin.get(f"/api/meals/{m['id']}").status_code == 404
    assert a.patch(f"/api/meals/{m['id']}", json={"shared": True}).json()["shared"] is True
    assert admin.delete(f"/api/meals/{m['id']}").status_code == 200
    assert ids(a) == []


def test_duplicate_makes_a_private_copy_of_mine(env):
    a, b = env["a"], env["b"]
    m, f = recipe(env, shared=True)
    a.patch(f"/api/meals/{m['id']}", json={"servings": 2, "yield": {"amount": 300, "unit": "g"}})
    r = b.post(f"/api/meals/{m['id']}/duplicate")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"] != m["id"] and d["name"] == "Toast (Copy)" and d["shared"] is False and d["mine"] is True
    assert d["owner"]["id"] == 2 and d["meals"] == ["breakfast"] and d["steps"] == ["Toast it"] and d["servings"] == 2
    assert d["yield"] == {"amount": 300, "unit": "g"} and d["counts"] == {}
    assert [(i["food_id"], i["amount"], i["src"] and i["src"]["text"]) for i in d["items"]] == [
        (f["id"], 2, None), (None, None, "butter to taste")]
    assert b.patch(f"/api/meals/{d['id']}", json={"name": "Bob Toast"}).status_code == 200
    assert a.get(f"/api/meals/{d['id']}").status_code == 404  # the copy is private to b
    assert a.get(f"/api/meals/{m['id']}").json()["name"] == "Toast"
    assert b.post(f"/api/meals/{m['id']}/duplicate", json={"name": " "}).status_code == 400
    assert b.post(f"/api/meals/{m['id']}/duplicate", json={"name": "Named"}).json()["name"] == "Named"
    assert a.post(f"/api/meals/{m['id']}/duplicate").json()["owner"]["id"] == 1  # the owner may copy too
    # a's custom food used in b's copy can no longer be deleted for everyone
    assert a.delete(f"/api/foods/{f['id']}").json()["everyone"] is False


def test_unshared_recipe_disappears_but_logs_stay(env):
    a, b = env["a"], env["b"]
    m, _ = recipe(env, shared=True)
    gid = b.post(f"/api/meals/{m['id']}/log", json={}).json()["group"]["group_id"]
    a.patch(f"/api/meals/{m['id']}", json={"shared": False})
    assert ids(b, "all") == []
    assert b.get(f"/api/entry-groups/{gid}").status_code == 200
    assert b.post(f"/api/entry-groups/{gid}/copy", json={"meal": "lunch"}).status_code == 200


def test_recipe_owner_display_setting(env):
    b = env["b"]
    assert b.get("/api/settings/display").json()["recipe_owner"] == "mine"
    for v in ("shared", "all", "mine"):
        assert b.put("/api/settings/display", json={"recipe_owner": v}).json()["recipe_owner"] == v
    for v in ("x", None, 1, ["all"]):
        assert b.put("/api/settings/display", json={"recipe_owner": v}).status_code == 400
    assert env["a"].get("/api/settings/display").json()["recipe_owner"] == "mine"


def test_saved_screen_lists_only_my_recipes(env):
    m, _ = recipe(env, shared=True)
    assert env["b"].get("/api/saved").json()["recipes"] == []
    assert [r["id"] for r in env["a"].get("/api/saved").json()["recipes"]] == [m["id"]]
