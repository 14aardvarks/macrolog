"""Photos on foods and recipes (app/photos.py): upload validation, permissions, visibility, serving, file handling.
a (id 1) owns the items, b (id 2) is another user, admin (id 3) is an admin (see tests/test_recipe_share.py)."""
import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image

from app import config, core, db, deps, lookup, photos
from tests.test_core import BREAD


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLOW_PHOTOS", "1")
    with db.conn() as c:
        db.init_shared(c)
        config.init(c)
        core.init(c)
        c.execute("INSERT INTO users(id, username, display_name, is_admin) VALUES (1, 'ann', 'Ann', 0), (2, 'bob', '', 0), (3, 'root', 'Root', 1)")

    async def nothing(*a, **k):
        return []

    monkeypatch.setattr(lookup, "search", nothing)
    monkeypatch.setattr(lookup, "search_off", nothing)
    api = FastAPI()
    api.include_router(core.router)
    api.include_router(photos.router)

    def fake_user(request: Request):
        uid = int(request.headers["x-user"])
        return {"id": uid, "username": "u", "display_name": "U", "is_admin": uid == 3}

    api.dependency_overrides[deps.current_user] = fake_user
    out = {k: TestClient(api, headers={"x-user": str(i)}) for k, i in (("a", 1), ("b", 2), ("admin", 3))}
    out["dir"] = tmp_path / "photos"
    return out


def image(fmt="JPEG", size=(40, 30), color=(200, 30, 30), mode="RGB", **kw) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt, **kw)
    return buf.getvalue()


def upload(client, path, data, name="x.jpg", ctype="image/jpeg"):
    return client.post(path, files={"photo": (name, data, ctype)})


def custom_food(client):
    r = client.post("/api/foods", json=BREAD)
    assert r.status_code == 200, r.text
    return r.json()


def recipe(client, shared=False):
    f = custom_food(client)
    m = client.post("/api/meals", json={"name": "Toast", "items": [{"food_id": f["id"], "amount": 2, "unit": "slice"}]}).json()
    if shared:
        client.patch(f"/api/meals/{m['id']}", json={"shared": True})
    return m


def files(env):
    return sorted(p.name for p in env["dir"].glob("*")) if env["dir"].exists() else []


def stored(env, name) -> Image.Image:
    with Image.open(env["dir"] / name) as im:
        im.load()
        return im


# ---------- validation ----------

@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_jpeg_png_webp_are_reencoded_as_jpeg(env, fmt):
    a = env["a"]
    f = custom_food(a)
    r = upload(a, f"/api/foods/{f['id']}/photo", image(fmt), ctype="application/octet-stream", name="evil.html")
    assert r.status_code == 200, r.text
    name = r.json()["photo"]
    assert photos.valid_name(name) and files(env) == [name]
    im = stored(env, name)
    assert im.format == "JPEG" and im.size == (40, 30)
    assert a.get(f"/api/foods/{f['id']}").json()["photo"] == name


def test_transparent_png_gets_a_white_background(env):
    a = env["a"]
    f = custom_food(a)
    name = upload(a, f"/api/foods/{f['id']}/photo", image("PNG", mode="RGBA", color=(0, 0, 0, 0))).json()["photo"]
    assert stored(env, name).convert("RGB").getpixel((5, 5))[0] > 240


@pytest.mark.parametrize("data", [b"GIF89a" + b"\0" * 100, b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"%PDF-1.4 hello"])
def test_other_types_are_refused_whatever_the_content_type(env, data):
    a = env["a"]
    f = custom_food(a)
    r = upload(a, f"/api/foods/{f['id']}/photo", data, ctype="image/jpeg")
    assert r.status_code == 400 and "JPEG, PNG and WebP" in r.json()["detail"]
    assert files(env) == []


def test_gif_with_a_jpeg_name_is_refused(env):
    buf = io.BytesIO()
    Image.new("RGB", (5, 5)).save(buf, "GIF")
    f = custom_food(env["a"])
    assert upload(env["a"], f"/api/foods/{f['id']}/photo", buf.getvalue(), name="a.jpg").status_code == 400


def test_corrupt_file_is_a_clear_400(env):
    a = env["a"]
    f = custom_food(a)
    data = image("JPEG", size=(200, 200))
    for broken in (data[:40], b"\xff\xd8\xff" + b"\0" * 500, image("PNG")[:30]):
        r = upload(a, f"/api/foods/{f['id']}/photo", broken)
        assert r.status_code == 400 and "readable" in r.json()["detail"], r.text
    assert upload(a, f"/api/foods/{f['id']}/photo", b"").status_code == 400
    assert a.post(f"/api/foods/{f['id']}/photo").status_code == 400  # no file
    assert files(env) == []


def test_upload_size_limit_follows_the_setting(env, monkeypatch):
    a = env["a"]
    f = custom_food(a)
    monkeypatch.setenv("PHOTO_MAX_MB", "1")
    big = image("PNG", size=(10, 10)) + b"\0" * (1024 * 1024)  # trailing bytes after a valid PNG, over 1 MB
    r = upload(a, f"/api/foods/{f['id']}/photo", big)
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    monkeypatch.setenv("PHOTO_MAX_MB", "99")  # out of bounds reads as the upper bound
    assert photos.max_mb() == 20
    monkeypatch.setenv("PHOTO_MAX_MB", "nonsense")
    assert photos.max_mb() == 5


def test_decompression_bomb_is_refused_before_decoding(env, monkeypatch):
    a = env["a"]
    f = custom_food(a)
    monkeypatch.setattr(photos, "PHOTO_MAX_PIXELS", 10_000)
    r = upload(a, f"/api/foods/{f['id']}/photo", image("PNG", size=(200, 200)))
    assert r.status_code == 400 and "too large" in r.json()["detail"]
    # a real bomb: a tiny PNG declaring a huge canvas trips Pillow's own guard too
    monkeypatch.setattr(photos, "PHOTO_MAX_PIXELS", 10 ** 12)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)
    r = upload(a, f"/api/foods/{f['id']}/photo", image("PNG", size=(300, 300)))
    assert r.status_code == 400 and "too large" in r.json()["detail"]
    assert files(env) == []


def test_large_dimensions_are_resized_to_1600(env):
    a = env["a"]
    f = custom_food(a)
    name = upload(a, f"/api/foods/{f['id']}/photo", image("JPEG", size=(3200, 1000))).json()["photo"]
    assert stored(env, name).size == (1600, 500)


def test_exif_is_applied_then_stripped(env):
    a = env["a"]
    f = custom_food(a)
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees clockwise to display
    exif[0x010F] = "SecretCam"  # Make
    exif[0x8825] = {2: (1.0, 2.0, 3.0)}  # GPS
    data = image("JPEG", size=(60, 20), exif=exif.tobytes())
    assert b"SecretCam" in data
    name = upload(a, f"/api/foods/{f['id']}/photo", data).json()["photo"]
    raw = (env["dir"] / name).read_bytes()
    im = stored(env, name)
    assert im.size == (20, 60)  # turned upright
    assert not im.getexif() and b"SecretCam" not in raw and b"Exif" not in raw


# ---------- permissions and switch ----------

def test_food_photo_permissions(env):
    a, b, admin = env["a"], env["b"], env["admin"]
    f = custom_food(a)
    assert upload(b, f"/api/foods/{f['id']}/photo", image()).status_code == 403
    assert upload(a, f"/api/foods/{f['id']}/photo", image()).status_code == 200
    assert b.delete(f"/api/foods/{f['id']}/photo").status_code == 403
    assert upload(admin, f"/api/foods/{f['id']}/photo", image()).status_code == 200
    assert admin.delete(f"/api/foods/{f['id']}/photo").status_code == 200
    assert upload(a, "/api/foods/999/photo", image()).status_code == 404
    with db.conn() as c:  # a shared database food has no creator: admin only
        c.execute("UPDATE foods SET source='off', source_id='1', created_by=NULL WHERE id=?", (f["id"],))
    assert upload(a, f"/api/foods/{f['id']}/photo", image()).status_code == 403
    assert upload(admin, f"/api/foods/{f['id']}/photo", image()).status_code == 200


def test_recipe_photo_permissions(env):
    a, b, admin = env["a"], env["b"], env["admin"]
    private = recipe(a)
    shared = recipe(a, shared=True)
    assert upload(b, f"/api/meals/{private['id']}/photo", image()).status_code == 404
    assert upload(admin, f"/api/meals/{private['id']}/photo", image()).status_code == 404
    assert upload(b, f"/api/meals/{shared['id']}/photo", image()).status_code == 403
    assert upload(admin, f"/api/meals/{shared['id']}/photo", image()).status_code == 200
    assert upload(a, f"/api/meals/{private['id']}/photo", image()).status_code == 200
    assert b.delete(f"/api/meals/{shared['id']}/photo").status_code == 403
    assert files(env) and len(files(env)) == 2


def test_switch_off_hides_everything(env, monkeypatch):
    a = env["a"]
    f = custom_food(a)
    name = upload(a, f"/api/foods/{f['id']}/photo", image()).json()["photo"]
    monkeypatch.setenv("ALLOW_PHOTOS", "0")
    assert a.get("/api/photo-config").json() == {"enabled": False, "max_mb": 5, "max_side": 1600}
    assert upload(a, f"/api/foods/{f['id']}/photo", image()).status_code == 403
    assert a.delete(f"/api/foods/{f['id']}/photo").status_code == 403
    assert a.get(f"/api/photos/{name}").status_code == 403
    assert files(env) == [name]  # nothing is deleted by the switch


def test_switch_defaults_off():
    assert config.MANAGED["allow_photos"].default == "0"
    assert not photos.enabled()
    spec = config.MANAGED["photo_max_mb"]
    assert (spec.default, spec.lo, spec.hi) == ("5", 1, 20)


# ---------- serving and visibility ----------

def test_serve_headers_and_food_visibility(env):
    a, b = env["a"], env["b"]
    f = custom_food(a)
    name = upload(a, f"/api/foods/{f['id']}/photo", image()).json()["photo"]
    for client in (a, b):  # foods are shared: every signed in user sees the photo
        r = client.get(f"/api/photos/{name}")
        assert r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff"
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
        assert r.headers["x-content-type-options"] == "nosniff"


def test_recipe_photo_visibility(env):
    a, b = env["a"], env["b"]
    m = recipe(a)
    name = upload(a, f"/api/meals/{m['id']}/photo", image()).json()["photo"]
    assert a.get(f"/api/meals/{m['id']}").json()["photo"] == name
    assert a.get(f"/api/photos/{name}").status_code == 200
    assert b.get(f"/api/photos/{name}").status_code == 404  # private
    a.patch(f"/api/meals/{m['id']}", json={"shared": True})
    assert b.get(f"/api/photos/{name}").status_code == 200
    a.delete(f"/api/meals/{m['id']}")  # Recently Deleted: the owner still sees it, others do not
    assert a.get(f"/api/photos/{name}").status_code == 200
    assert b.get(f"/api/photos/{name}").status_code == 404
    assert a.get("/api/meals/deleted").json()["meals"][0]["photo"] == name


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "..%2Ft.db", "t.db", "%2E%2E", "a" * 30 + ".png",
                                 "a" * 30 + ".jpg.tmp", "..", "a" * 30 + "%00.jpg"])
def test_serve_route_refuses_traversal_and_odd_names(env, bad):
    a = env["a"]
    (env["dir"]).mkdir(exist_ok=True)
    assert a.get(f"/api/photos/{bad}").status_code == 404


def test_unreferenced_file_is_not_served(env):
    env["dir"].mkdir()
    name = "A" * 32 + ".jpg"
    (env["dir"] / name).write_bytes(image())
    assert env["a"].get(f"/api/photos/{name}").status_code == 404


# ---------- file handling ----------

def test_replace_deletes_the_old_file_and_delete_removes_it(env):
    a = env["a"]
    m = recipe(a)
    first = upload(a, f"/api/meals/{m['id']}/photo", image()).json()["photo"]
    second = upload(a, f"/api/meals/{m['id']}/photo", image("PNG")).json()["photo"]
    assert first != second and files(env) == [second]
    assert a.delete(f"/api/meals/{m['id']}/photo").json() == {"photo": None}
    assert files(env) == [] and a.get(f"/api/meals/{m['id']}").json()["photo"] is None
    assert a.delete(f"/api/meals/{m['id']}/photo").status_code == 200  # nothing left: still fine


def test_failed_upload_keeps_the_old_photo(env):
    a = env["a"]
    f = custom_food(a)
    name = upload(a, f"/api/foods/{f['id']}/photo", image()).json()["photo"]
    assert upload(a, f"/api/foods/{f['id']}/photo", b"junk").status_code == 400
    assert files(env) == [name] and a.get(f"/api/foods/{f['id']}").json()["photo"] == name


def test_duplicate_copies_restore_keeps_purge_deletes(env):
    a, b = env["a"], env["b"]
    m = recipe(a, shared=True)
    name = upload(a, f"/api/meals/{m['id']}/photo", image()).json()["photo"]
    copy = b.post(f"/api/meals/{m['id']}/duplicate", json={}).json()
    assert copy["photo"] and copy["photo"] != name and len(files(env)) == 2
    assert b.get(f"/api/photos/{copy['photo']}").status_code == 200
    a.delete(f"/api/meals/{m['id']}")
    assert a.post(f"/api/meals/{m['id']}/restore").json()["photo"] == name
    a.delete(f"/api/meals/{m['id']}")
    assert a.delete(f"/api/meals/{m['id']}/purge").status_code == 200
    assert files(env) == [copy["photo"]]  # the copy is its own file


def test_auto_purge_deletes_the_file(env):
    a = env["a"]
    m = recipe(a)
    upload(a, f"/api/meals/{m['id']}/photo", image())
    a.delete(f"/api/meals/{m['id']}")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with db.conn() as c:
        c.execute("UPDATE meals SET deleted_at=? WHERE id=?", (old, m["id"]))
    a.get("/api/meals")
    assert files(env) == []


def test_food_delete_keeps_the_photo(env):
    a = env["a"]
    f = custom_food(a)
    name = upload(a, f"/api/foods/{f['id']}/photo", image()).json()["photo"]
    a.delete(f"/api/foods/{f['id']}")
    assert files(env) == [name]


def test_photo_appears_in_lists(env):
    a = env["a"]
    m = recipe(a)
    f = a.get("/api/saved").json()["foods"][0]
    name = upload(a, f"/api/foods/{f['id']}/photo", image()).json()["photo"]
    mname = upload(a, f"/api/meals/{m['id']}/photo", image()).json()["photo"]
    saved = a.get("/api/saved").json()
    assert saved["foods"][0]["photo"] == name and saved["recipes"][0]["photo"] == mname
    assert a.get("/api/meals").json()["meals"][0]["photo"] == mname


def test_migration_adds_photo_columns_and_keeps_rows(tmp_path):
    c = sqlite3.connect(tmp_path / "old.db")
    c.row_factory = sqlite3.Row
    c.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, display_name TEXT);"
        "CREATE TABLE meals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT, meal TEXT);"
        "CREATE TABLE foods(id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT, name TEXT NOT NULL, brand TEXT,"
        " serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL, serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',"
        " kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL);"
        "INSERT INTO meals(id, user_id, name) VALUES(7, 1, 'Old');"
        "INSERT INTO foods(id, source, name, serving_amount, serving_unit, kcal, carbs, protein, fat) VALUES(4, 'custom', 'Egg', 1, 'piece', 70, 0, 6, 5);")
    core.init(c)
    core.init(c)  # safe to run twice
    for table in ("foods", "meals"):
        assert "photo" in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    assert c.execute("SELECT name, photo FROM meals WHERE id=7").fetchone()[:] == ("Old", None)
    assert core.food_dict(c.execute("SELECT * FROM foods WHERE id=4").fetchone())["photo"] is None
    c.close()
