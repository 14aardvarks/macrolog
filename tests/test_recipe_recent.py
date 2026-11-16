"""Recipes list order (#51): recipes carry created_at and updated_at so the client can sort by last edited, falling back to created."""
import sqlite3

from app import core, db
from tests.test_core import BREAD
from tests.test_recipe_share import env, food, recipe  # noqa: F401 (env is a fixture)


def stamp(client, meal_id):
    m = client.get(f"/api/meals/{meal_id}").json()
    return m["updated_at"], m["created_at"]


def test_new_recipe_has_created_and_no_updated(env):
    m, _ = recipe(env)
    got = env["a"].get(f"/api/meals/{m['id']}").json()
    assert got["created_at"] and got["updated_at"] is not None  # recipe() adds a row after saving, which is an edit
    fresh = env["a"].post("/api/meals", json={"name": "Plain", "items": [{"food_id": m["items"][0]["food_id"], "amount": 1, "unit": "slice"}]}).json()
    assert fresh["created_at"] and fresh["updated_at"] is None


def test_edits_set_updated_at_and_other_actions_do_not(env):
    a = env["a"]
    m, f = recipe(env)
    mid = m["id"]
    item = a.get(f"/api/meals/{mid}").json()["items"][0]

    def clear():
        with db.conn() as c:
            c.execute("UPDATE meals SET updated_at=NULL WHERE id=?", (mid,))

    def touched():
        with db.conn() as c:
            return c.execute("SELECT updated_at FROM meals WHERE id=?", (mid,)).fetchone()[0] is not None

    for body in ({"name": "Toast 2"}, {"meals": ["lunch"]}, {"servings": 3}, {"steps": ["a"]}, {"yield": {"amount": 100, "unit": "g"}}):
        clear()
        assert a.patch(f"/api/meals/{mid}", json=body).status_code == 200
        assert touched(), body
    clear()
    assert a.patch(f"/api/meals/{mid}/items/{item['id']}", json={"skipped": True}).status_code == 200 and touched()
    clear()
    added = a.post(f"/api/meals/{mid}/items", json={"src": {"name": "salt"}}).json()["added"]
    assert touched()
    clear()
    assert a.delete(f"/api/meals/{mid}/items/{added}").status_code == 200 and touched()
    for body in ({"shared": True}, {"match_prompt_dismissed": True}):  # not content edits
        clear()
        assert a.patch(f"/api/meals/{mid}", json=body).status_code == 200
        assert not touched(), body
    clear()
    a.post(f"/api/meals/{mid}/log", json={"meal": "lunch"})
    assert not touched()


def test_updated_at_sorts_after_created_as_text(env):
    a = env["a"]
    f = food(a, BREAD)
    one = a.post("/api/meals", json={"name": "One", "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).json()
    two = a.post("/api/meals", json={"name": "Two", "items": [{"food_id": f["id"], "amount": 1, "unit": "slice"}]}).json()
    a.patch(f"/api/meals/{one['id']}", json={"name": "One edited"})
    u, c = stamp(a, one["id"])
    assert u > stamp(a, two["id"])[1] and len(u) > len(c)  # same "YYYY-MM-DD HH:MM:SS" shape, with fractions


def test_migration_adds_updated_at_and_keeps_rows(tmp_path):
    c = sqlite3.connect(tmp_path / "old.db")
    c.row_factory = sqlite3.Row
    c.executescript("CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, meal TEXT);"
                    "INSERT INTO meals(id, user_id, name) VALUES(1, 1, 'Old');")
    core.init(c)
    core.init(c)
    assert c.execute("SELECT name, updated_at FROM meals").fetchone()[:] == ("Old", None)
