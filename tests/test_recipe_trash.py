"""Recently Deleted (#41): DELETE /api/meals/{id} is a soft delete with restore, purge and a 30 day auto purge.
a (id 1) owns the recipes, b (id 2) is another user, admin (id 3) is an admin (see tests/test_recipe_share.py)."""
import sqlite3
from datetime import datetime, timedelta, timezone

from app import core, db, recipe_ai
from tests.test_core import BREAD
from tests.test_recipe_share import TODAY, env, food, ids, recipe  # noqa: F401 (env is a fixture)


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="microseconds")


def set_deleted_at(meal_id: int, stamp: str) -> None:
    with db.conn() as c:
        c.execute("UPDATE meals SET deleted_at=? WHERE id=?", (stamp, meal_id))


def rows(table: str, meal_id: int) -> int:
    with db.conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table} WHERE {'id' if table == 'meals' else 'meal_id'}=?", (meal_id,)).fetchone()[0]


def full_recipe(env, shared=False):
    """a's recipe with tags, steps, servings, yield, an unmatched line, a log count and optionally shared."""
    a = env["a"]
    m, f = recipe(env, shared=shared)
    a.patch(f"/api/meals/{m['id']}", json={"servings": 4, "yield": {"amount": 800, "unit": "g"}, "meals": ["breakfast", "snack"]})
    a.post(f"/api/meals/{m['id']}/log", json={"meal": "lunch"})
    return a.get(f"/api/meals/{m['id']}").json(), f


def test_migration_adds_deleted_at_and_keeps_rows(tmp_path):
    c = sqlite3.connect(tmp_path / "old.db")
    c.row_factory = sqlite3.Row
    c.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, display_name TEXT);"
        "CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT, meal TEXT);"
        "CREATE TABLE meal_items(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL, food_id INTEGER NOT NULL, amount REAL NOT NULL,"
        " unit TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO meals(id, user_id, name) VALUES(7, 1, 'Old');"
        "INSERT INTO meal_items(meal_id, food_id, amount, unit) VALUES(7, 3, 2, 'slice');")
    core.init(c)
    core.init(c)  # safe to run twice
    assert "deleted_at" in {r[1] for r in c.execute("PRAGMA table_info(meals)")}
    assert c.execute("SELECT name, deleted_at FROM meals WHERE id=7").fetchone()[:] == ("Old", None)
    assert c.execute("SELECT COUNT(*) FROM meal_items WHERE meal_id=7").fetchone()[0] == 1


def test_delete_is_soft_and_hides_the_recipe_everywhere(env):
    a, b = env["a"], env["b"]
    m, f = full_recipe(env, shared=True)
    mid, item = m["id"], m["items"][0]["id"]
    r = a.delete(f"/api/meals/{mid}")
    assert r.status_code == 200 and r.json()["deleted"] == mid and r.json()["days_left"] == 30 and r.json()["purge_days"] == 30
    for t in ("meals", "meal_items", "recipe_tags", "recipe_logs"):
        assert rows(t, mid) > 0, t  # nothing removed
    for client in (a, b):
        for owner in ("mine", "shared", "all"):
            assert mid not in ids(client, owner)
        assert client.get(f"/api/meals/{mid}").status_code == 404
        assert client.post(f"/api/meals/{mid}/log", json={}).status_code == 404
        assert client.post(f"/api/meals/{mid}/duplicate").status_code == 404
    assert a.get("/api/saved").json()["recipes"] == []
    assert a.patch(f"/api/meals/{mid}", json={"name": "X"}).status_code == 404
    assert a.patch(f"/api/meals/{mid}/items/{item}", json={"skipped": True}).status_code == 404
    assert a.patch(f"/api/meals/{mid}/items", json={"items": [{"id": item, "skipped": True}]}).status_code == 404
    assert a.post(f"/api/meals/{mid}/items", json={"src": {"name": "jam"}}).status_code == 404
    assert a.delete(f"/api/meals/{mid}/items/{item}").status_code == 404
    assert a.delete(f"/api/meals/{mid}/uncounted").status_code == 404
    assert a.delete(f"/api/meals/{mid}").status_code == 404  # already deleted
    assert a.post(f"/api/recipes/{mid}/match-search", json={"item_ids": [item]}).status_code == 404
    assert a.post(f"/api/recipes/{mid}/match", json={"item_ids": [item]}).status_code == 404


def test_previous_matches_skip_deleted_recipes(env):
    a = env["a"]
    f = food(a, BREAD)
    m = a.post("/api/meals/import", json={"name": "Sandwich", "ingredients": [{"name": "bread"}]}).json()
    assert a.patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"food_id": f["id"], "amount": 1, "unit": "slice"}).status_code == 200
    assert recipe_ai.previous_matches(1, ["bread"])["bread"]["id"] == f["id"]
    a.delete(f"/api/meals/{m['id']}")
    assert recipe_ai.previous_matches(1, ["bread"]) == {}
    a.post(f"/api/meals/{m['id']}/restore")
    assert recipe_ai.previous_matches(1, ["bread"])["bread"]["id"] == f["id"]


def test_logged_entries_survive_delete_and_purge(env):
    a = env["a"]
    m, _ = full_recipe(env)
    log = a.post(f"/api/meals/{m['id']}/log", json={"meal": "dinner", "day": TODAY}).json()
    gid = log["group"]["group_id"]
    before = a.get("/api/day", params={"day": TODAY}).json()
    a.delete(f"/api/meals/{m['id']}")
    for step in ("deleted", "purged"):
        day = a.get("/api/day", params={"day": TODAY}).json()
        assert day["totals"] == before["totals"], step
        group = next(x for x in day["entries"] if x.get("group_id") == gid)
        assert group["name"] == "Toast" and group["kcal"] == log["group"]["kcal"]
        assert a.get(f"/api/entry-groups/{gid}").status_code == 200
        if step == "deleted":
            assert a.delete(f"/api/meals/{m['id']}/purge").status_code == 200
    assert a.patch(f"/api/entry-groups/{gid}", json={"amount": 2, "unit": "serving"}).status_code == 200
    copy = a.post(f"/api/entry-groups/{gid}/copy", json={"meal": "snack"})
    assert copy.status_code == 200 and copy.json()["name"] == "Toast"


def test_log_copy_of_a_deleted_recipe_does_not_count_or_tag(env):
    a = env["a"]
    m, _ = full_recipe(env)
    gid = a.post(f"/api/meals/{m['id']}/log", json={"meal": "dinner"}).json()["group"]["group_id"]
    a.delete(f"/api/meals/{m['id']}")
    assert a.post(f"/api/entry-groups/{gid}/copy", json={"meal": "dessert"}).status_code == 200
    back = a.post(f"/api/meals/{m['id']}/restore").json()
    assert "dessert" not in back["meals"] and "dessert" not in back["counts"]


def test_restore_brings_everything_back_exactly(env):
    a, b = env["a"], env["b"]
    m, _ = full_recipe(env, shared=True)
    a.delete(f"/api/meals/{m['id']}")
    r = a.post(f"/api/meals/{m['id']}/restore")
    assert r.status_code == 200
    assert r.json() == m
    assert a.get(f"/api/meals/{m['id']}").json() == m
    assert m["shared"] is True and m["servings"] == 4 and m["yield"] == {"amount": 800, "unit": "g"}
    assert m["steps"] == ["Toast it"] and m["meals"] == ["breakfast", "lunch", "snack"] and len(m["items"]) == 2
    assert m["id"] in ids(b, "shared") and m["id"] in ids(a)
    assert a.post(f"/api/meals/{m['id']}/restore").status_code == 409  # not deleted any more


def test_deleted_list_is_own_newest_first_with_days_left(env):
    a, b = env["a"], env["b"]
    m1, _ = recipe(env, shared=True)
    m2 = a.post("/api/meals/import", json={"name": "Soup", "ingredients": [{"name": "water"}]}).json()
    assert a.get("/api/meals/deleted").json() == {"meals": [], "purge_days": 30}
    a.delete(f"/api/meals/{m1['id']}")
    a.delete(f"/api/meals/{m2['id']}")
    set_deleted_at(m1["id"], ago(10.5))
    got = a.get("/api/meals/deleted").json()
    assert [x["id"] for x in got["meals"]] == [m2["id"], m1["id"]]
    assert [x["days_left"] for x in got["meals"]] == [30, 20]
    assert got["meals"][0]["name"] == "Soup" and got["meals"][0]["deleted_at"]
    assert b.get("/api/meals/deleted").json()["meals"] == []  # only own deleted recipes, shared or not
    assert env["admin"].get("/api/meals/deleted").json()["meals"] == []


def test_permissions_for_restore_and_purge(env):
    a, b, admin = env["a"], env["b"], env["admin"]
    private, _ = recipe(env)
    shared, _ = recipe(env, shared=True)
    for m in (private, shared):
        a.delete(f"/api/meals/{m['id']}")
    for client in (b, admin):  # someone else's private recipe: never there
        assert client.post(f"/api/meals/{private['id']}/restore").status_code == 404
        assert client.delete(f"/api/meals/{private['id']}/purge").status_code == 404
    assert b.post(f"/api/meals/{shared['id']}/restore").status_code == 403
    assert b.delete(f"/api/meals/{shared['id']}/purge").status_code == 403
    assert admin.post(f"/api/meals/{shared['id']}/restore").status_code == 200
    assert b.delete(f"/api/meals/{shared['id']}").status_code == 403  # delete has the same rule
    assert admin.delete(f"/api/meals/{shared['id']}").status_code == 200
    assert admin.delete(f"/api/meals/{shared['id']}/purge").status_code == 200
    assert rows("meals", shared["id"]) == 0
    assert a.post("/api/meals/999/restore").status_code == 404
    assert a.delete("/api/meals/999/purge").status_code == 404


def test_purge_only_when_deleted_and_removes_every_row(env):
    a = env["a"]
    m, _ = full_recipe(env)
    assert a.delete(f"/api/meals/{m['id']}/purge").status_code == 409  # delete it first
    assert a.get(f"/api/meals/{m['id']}").status_code == 200
    a.delete(f"/api/meals/{m['id']}")
    assert a.delete(f"/api/meals/{m['id']}/purge").json() == {"purged": m["id"]}
    for t in ("meals", "meal_items", "recipe_tags", "recipe_logs"):
        assert rows(t, m["id"]) == 0, t
    assert a.post(f"/api/meals/{m['id']}/restore").status_code == 404
    assert a.get("/api/meals/deleted").json()["meals"] == []


def test_auto_purge_after_30_days_on_listing_and_startup(env):
    a = env["a"]
    old, _ = recipe(env)
    young, _ = recipe(env)
    kept, _ = recipe(env)
    for m in (old, young):
        a.delete(f"/api/meals/{m['id']}")
    set_deleted_at(old["id"], ago(30.01))
    set_deleted_at(young["id"], ago(29.5))
    assert ids(a) == [kept["id"]]  # listing purges
    assert rows("meals", old["id"]) == 0 and rows("meal_items", old["id"]) == 0
    got = a.get("/api/meals/deleted").json()["meals"]
    assert [x["id"] for x in got] == [young["id"]] and got[0]["days_left"] == 1
    set_deleted_at(young["id"], ago(31))
    with db.conn() as c:
        core.init(c)  # startup
    assert rows("meals", young["id"]) == 0 and rows("meals", kept["id"]) == 1


def test_days_left_helper():
    assert core.RECIPE_PURGE_DAYS == 30
    assert core.days_left(ago(0)) == 30
    assert core.days_left(ago(29.9)) == 1
    assert core.days_left(ago(40)) == 0
    assert core.days_left("2026-01-01 00:00:00") == 0  # naive text reads as UTC
    assert core.days_left("nonsense") == 0
