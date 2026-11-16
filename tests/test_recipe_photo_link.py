"""Recipe photo by link (#52): meals.photo_url, validated on the server and never fetched, and the once per recipe photo prompt
after a log (meals.photo_prompt_dismissed). a (id 1) owns the recipes, b (id 2) is another user, admin (id 3) is an admin."""
import socket
import sqlite3

import pytest

from app import core, db
from tests.test_photos import custom_food, env, files, image, recipe, upload  # noqa: F401 (env is a fixture)

LINK = "https://example.com/pics/toast.jpg"


def patch(client, mid, **body):
    return client.patch(f"/api/meals/{mid}", json=body)


def log(client, mid, **body):
    r = client.post(f"/api/meals/{mid}/log", json={"meal": "lunch", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_new_recipe_has_no_link_and_no_dismissal(env):
    m = recipe(env["a"])
    assert m["photo_url"] is None and m["photo_prompt_dismissed"] is False


@pytest.mark.parametrize("url", [LINK, "http://example.com/a.png", "HTTPS://EXAMPLE.COM/x", "https://example.com:8443/p?q=1&r=2#f",
                                 "https://127.0.0.1/x.jpg", "https://[::1]/x.jpg", "  " + LINK + "  "])
def test_good_links_are_stored(env, url):
    a = env["a"]
    m = recipe(a)
    r = patch(a, m["id"], photo_url=url)
    assert r.status_code == 200, r.text
    assert r.json()["photo_url"] == url.strip()
    assert a.get(f"/api/meals/{m['id']}").json()["photo_url"] == url.strip()
    assert [x for x in a.get("/api/meals").json()["meals"] if x["id"] == m["id"]][0]["photo_url"] == url.strip()


@pytest.mark.parametrize("url", ["ftp://example.com/x.jpg", "javascript:alert(1)", "data:image/png;base64,AAAA", "file:///etc/passwd",
                                 "//example.com/x.jpg", "example.com/x.jpg", "http://", "https:///x", "https://user:pw@example.com/x.jpg",
                                 "https://@example.com/x", "https://example.com/a b", "https://example.com/a\nb", "https://example.com/<x>",
                                 'https://example.com/"x', "https://example.com/'x", "https://example.com:99999/x", "https://exa mple.com/x",
                                 "blob:https://example.com/1", 42, True, ["https://example.com/x"], {"u": 1}])
def test_bad_links_are_refused(env, url):
    a = env["a"]
    m = recipe(a)
    patch(a, m["id"], photo_url=LINK)
    r = patch(a, m["id"], photo_url=url)
    assert r.status_code == 400, url
    assert a.get(f"/api/meals/{m['id']}").json()["photo_url"] == LINK  # the old link is kept


def test_link_length_limit(env):
    a = env["a"]
    m = recipe(a)
    base = "https://example.com/"
    ok = base + "x" * (core.PHOTO_URL_MAX - len(base))
    assert patch(a, m["id"], photo_url=ok).status_code == 200
    assert patch(a, m["id"], photo_url=ok + "x").status_code == 400


def test_blank_or_null_clears_the_link(env):
    a = env["a"]
    m = recipe(a)
    patch(a, m["id"], photo_url=LINK)
    assert patch(a, m["id"], photo_url=None).json()["photo_url"] is None
    patch(a, m["id"], photo_url=LINK)
    assert patch(a, m["id"], photo_url="   ").json()["photo_url"] is None


def test_the_server_never_fetches_the_link(env, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("the server tried to open a connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    a = env["a"]
    m = recipe(a)
    assert patch(a, m["id"], photo_url="http://169.254.169.254/latest/meta-data/").status_code == 200  # stored text only
    assert a.get(f"/api/meals/{m['id']}").status_code == 200


def test_a_link_needs_no_allow_photos_but_an_upload_does(env, monkeypatch):
    a = env["a"]
    m = recipe(a)
    monkeypatch.setenv("ALLOW_PHOTOS", "0")
    assert upload(a, f"/api/meals/{m['id']}/photo", image()).status_code == 403
    assert patch(a, m["id"], photo_url=LINK).json()["photo_url"] == LINK
    assert patch(a, m["id"], photo_url=None).json()["photo_url"] is None


def test_only_the_owner_or_an_admin_can_set_a_link(env):
    a, b, admin = env["a"], env["b"], env["admin"]
    m = recipe(a, shared=True)
    assert patch(b, m["id"], photo_url=LINK).status_code == 403
    assert patch(admin, m["id"], photo_url=LINK).status_code == 200
    private = recipe(a)
    assert patch(b, private["id"], photo_url=LINK).status_code == 404
    assert a.get(f"/api/meals/{private['id']}").json()["photo_url"] is None


def test_upload_and_link_can_both_be_stored_and_remove_clears_both(env):
    a = env["a"]
    m = recipe(a)
    patch(a, m["id"], photo_url=LINK)
    name = upload(a, f"/api/meals/{m['id']}/photo", image()).json()["photo"]
    got = a.get(f"/api/meals/{m['id']}").json()
    assert got["photo"] == name and got["photo_url"] == LINK  # the client shows the upload; both stay stored
    assert a.delete(f"/api/meals/{m['id']}/photo").status_code == 200
    got = a.get(f"/api/meals/{m['id']}").json()
    assert got["photo"] is None and got["photo_url"] is None and files(env) == []


def test_remove_with_photos_off_clears_the_link_through_patch(env, monkeypatch):
    a = env["a"]
    m = recipe(a)
    patch(a, m["id"], photo_url=LINK)
    monkeypatch.setenv("ALLOW_PHOTOS", "0")
    assert a.delete(f"/api/meals/{m['id']}/photo").status_code == 403
    assert patch(a, m["id"], photo_url=None).json()["photo_url"] is None


def test_duplicate_copies_the_link_but_not_the_dismissal(env):
    a, b = env["a"], env["b"]
    m = recipe(a, shared=True)
    patch(a, m["id"], photo_url=LINK, photo_prompt_dismissed=True)
    copy = b.post(f"/api/meals/{m['id']}/duplicate", json={}).json()
    assert copy["photo_url"] == LINK and copy["photo_prompt_dismissed"] is False
    plain = recipe(a)
    patch(a, plain["id"], photo_prompt_dismissed=True)
    assert a.post(f"/api/meals/{plain['id']}/duplicate", json={}).json()["photo_prompt_dismissed"] is False


def test_delete_and_restore_keep_the_link(env):
    a = env["a"]
    m = recipe(a)
    patch(a, m["id"], photo_url=LINK)
    a.delete(f"/api/meals/{m['id']}")
    assert a.post(f"/api/meals/{m['id']}/restore").json()["photo_url"] == LINK


def test_photo_changes_count_as_edits_for_the_recipes_order(env):
    a = env["a"]
    m = recipe(a)

    def updated():
        with db.conn() as c:
            return c.execute("SELECT updated_at FROM meals WHERE id=?", (m["id"],)).fetchone()[0]

    with db.conn() as c:
        c.execute("UPDATE meals SET updated_at=NULL WHERE id=?", (m["id"],))
    patch(a, m["id"], photo_url=LINK)
    assert updated()
    with db.conn() as c:
        c.execute("UPDATE meals SET updated_at=NULL WHERE id=?", (m["id"],))
    upload(a, f"/api/meals/{m['id']}/photo", image())
    assert updated()
    with db.conn() as c:
        c.execute("UPDATE meals SET updated_at=NULL WHERE id=?", (m["id"],))
    patch(a, m["id"], photo_prompt_dismissed=True)
    assert updated() is None  # a flag is not an edit


def test_patch_flag_validation(env):
    a = env["a"]
    m = recipe(a)
    for bad in ("yes", 1, None, [True]):
        assert patch(a, m["id"], photo_prompt_dismissed=bad).status_code == 400
    assert patch(a, m["id"], photo_prompt_dismissed=True).json()["photo_prompt_dismissed"] is True
    assert patch(a, m["id"], photo_prompt_dismissed=False).json()["photo_prompt_dismissed"] is False


# ---------- the prompt after a log ----------

def test_prompt_comes_once_for_a_recipe_without_a_photo(env):
    a = env["a"]
    m = recipe(a)
    first = log(a, m["id"])
    assert first["photo_prompt"] is True
    assert a.get(f"/api/meals/{m['id']}").json()["photo_prompt_dismissed"] is True  # remembered when shown
    assert log(a, m["id"])["photo_prompt"] is False
    assert log(a, m["id"])["photo_prompt"] is False


def test_no_prompt_when_the_recipe_has_an_upload_or_a_link(env):
    a = env["a"]
    up, link = recipe(a), recipe(a)
    upload(a, f"/api/meals/{up['id']}/photo", image())
    patch(a, link["id"], photo_url=LINK)
    assert log(a, up["id"])["photo_prompt"] is False
    assert log(a, link["id"])["photo_prompt"] is False


def test_no_prompt_when_allow_photos_is_off(env, monkeypatch):
    a = env["a"]
    m = recipe(a)
    monkeypatch.setenv("ALLOW_PHOTOS", "0")
    assert log(a, m["id"])["photo_prompt"] is False
    assert a.get(f"/api/meals/{m['id']}").json()["photo_prompt_dismissed"] is False  # not used up while it could not be shown
    monkeypatch.setenv("ALLOW_PHOTOS", "1")
    assert log(a, m["id"])["photo_prompt"] is True


def test_dismissed_recipes_are_not_asked(env):
    a = env["a"]
    m = recipe(a)
    patch(a, m["id"], photo_prompt_dismissed=True)
    assert log(a, m["id"])["photo_prompt"] is False
    patch(a, m["id"], photo_prompt_dismissed=False)
    assert log(a, m["id"])["photo_prompt"] is True


def test_only_the_owner_is_asked(env):
    a, b, admin = env["a"], env["b"], env["admin"]
    m = recipe(a, shared=True)
    assert log(b, m["id"])["photo_prompt"] is False
    assert log(admin, m["id"])["photo_prompt"] is False
    assert a.get(f"/api/meals/{m['id']}").json()["photo_prompt_dismissed"] is False
    assert log(a, m["id"])["photo_prompt"] is True


def test_a_duplicate_without_a_photo_asks_once_itself(env):
    a = env["a"]
    m = recipe(a)
    assert log(a, m["id"])["photo_prompt"] is True
    copy = a.post(f"/api/meals/{m['id']}/duplicate", json={}).json()
    assert log(a, copy["id"])["photo_prompt"] is True
    assert log(a, copy["id"])["photo_prompt"] is False


def test_a_failed_log_does_not_use_up_the_prompt(env):
    a = env["a"]
    m = recipe(a)
    assert a.post(f"/api/meals/{m['id']}/log", json={"meal": "nope"}).status_code == 400
    assert a.get(f"/api/meals/{m['id']}").json()["photo_prompt_dismissed"] is False


def test_migration_adds_both_columns_and_keeps_rows(tmp_path):
    c = sqlite3.connect(tmp_path / "old.db")
    c.row_factory = sqlite3.Row
    c.executescript("CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, meal TEXT);"
                    "INSERT INTO meals(id, user_id, name) VALUES(1, 1, 'Old');")
    core.init(c)
    core.init(c)
    row = c.execute("SELECT name, photo_url, photo_prompt_dismissed FROM meals").fetchone()
    assert tuple(row) == ("Old", None, None)
