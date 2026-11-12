"""Soft delete of foods, and the meal filter of the Recent list."""
from tests.test_core import BREAD, PB, SALT, a, b, env, food, log, off_food, TODAY  # noqa: F401

RICE = off_food(barcode="073472001011")


def day(client):
    return client.get("/api/day", params={"day": TODAY}).json()


def search_ids(client, q, **kw):
    return [f["id"] for f in client.get("/api/foods/search", params={"q": q, "remote": 0, **kw}).json()["results"]]


def test_delete_logged_food_keeps_entries_and_totals(a, env):
    f = food(a, SALT)
    log(a, f, amount=50)
    log(a, f, amount=100, meal="lunch")
    before = day(a)
    r = a.delete(f"/api/foods/{f['id']}")
    assert r.status_code == 200 and r.json() == {"deleted": f["id"], "everyone": True}
    after = day(a)
    assert after["entries"] == before["entries"] and after["totals"] == before["totals"]
    assert all(e["name"] == "Mystery" for e in after["entries"])
    assert a.get(f"/api/foods/{f['id']}").json()["name"] == "Mystery"  # entries and the picker still open it


def test_deleted_food_leaves_every_list(a):
    f = food(a)
    other = food(a, PB)
    a.post(f"/api/favorites/{f['id']}")
    log(a, f)
    assert f["id"] in search_ids(a, "bread")
    a.delete(f"/api/foods/{f['id']}")
    assert search_ids(a, "bread") == []
    assert search_ids(a, "bread", source="all") == []
    assert [i["food"]["id"] for i in a.get("/api/quick/favorites").json()["items"]] == []
    assert [i["food"]["id"] for i in a.get("/api/quick/recent").json()["items"]] == []
    assert a.get("/api/quick/yesterday", params={"day": TODAY}).json()["items"] == []
    saved = a.get("/api/saved").json()
    assert saved["favorites"] == [] and f["id"] not in [x["id"] for x in saved["foods"]] and other["id"] in [x["id"] for x in saved["foods"]]


def test_deleted_food_still_works_in_a_recipe(a):
    f = food(a, PB)
    m = a.post("/api/meals", json={"name": "Toast", "items": [{"food_id": f["id"], "amount": 2, "unit": "tbsp"}]}).json()
    before = a.get(f"/api/meals/{m['id']}").json()
    assert a.delete(f"/api/foods/{f['id']}").status_code == 200
    after = a.get(f"/api/meals/{m['id']}").json()
    assert after["items"][0]["food"]["name"] == "Peanut Butter" and after["totals"] == before["totals"]
    assert after["matched"] == before["matched"] and after["complete"] is True
    assert a.post(f"/api/meals/{m['id']}/log", json={"meal": "lunch"}).status_code == 200
    assert day(a)["totals"]["kcal"] == before["totals"]["kcal"]
    assert a.get("/api/saved").json()["recipes"][0]["name"] == "Toast"


def test_nutrition_of_logged_food_stays_locked_but_delete_is_not(a):
    f = food(a, SALT)
    log(a, f)
    assert a.patch(f"/api/foods/{f['id']}", json={"kcal": 5}).status_code == 409
    assert a.delete(f"/api/foods/{f['id']}").status_code == 200


def test_logging_favoriting_or_scanning_again_undeletes(a, env):
    f = food(a, {**PB, "barcode": "073472001011"})
    a.delete(f"/api/foods/{f['id']}")
    assert search_ids(a, "peanut") == []
    r = a.get("/api/foods/barcode/073472001011").json()  # the same barcode again: back as a normal food
    assert r["food"]["id"] == f["id"]
    assert f["id"] in search_ids(a, "peanut") and f["id"] in [x["id"] for x in a.get("/api/saved").json()["foods"]]
    a.delete(f"/api/foods/{f['id']}")
    log(a, f)
    assert f["id"] in search_ids(a, "peanut")
    a.delete(f"/api/foods/{f['id']}")
    assert a.post(f"/api/favorites/{f['id']}").status_code == 200
    assert f["id"] in search_ids(a, "peanut")


def test_undelete_when_a_recipe_picks_it_again(a):
    f = food(a, PB)
    m = a.post("/api/meals", json={"name": "R", "items": [{"food_id": f["id"], "amount": 1, "unit": "tbsp"}]}).json()
    a.delete(f"/api/foods/{f['id']}")
    assert search_ids(a, "peanut") == []
    a.post(f"/api/meals/{m['id']}/items", json={"food_id": f["id"], "amount": 1, "unit": "tbsp"})
    assert f["id"] in search_ids(a, "peanut")


def test_remote_food_deleted_by_one_user_only_hides_for_that_user(a, b, env):
    env["search_result"] = [RICE]
    shared = a.get("/api/foods/search", params={"q": "rice"}).json()["results"][0]
    log(a, shared, unit="cup")
    log(b, shared, unit="cup")
    r = a.delete(f"/api/foods/{shared['id']}")
    assert r.json()["everyone"] is False
    assert shared["id"] not in search_ids(a, "rice") and shared["id"] in search_ids(b, "rice")
    assert [i["food"]["id"] for i in b.get("/api/quick/recent").json()["items"]] == [shared["id"]]
    assert a.get("/api/quick/recent").json()["items"] == []
    assert day(b)["entries"][0]["name"] == "Remote Rice" and day(a)["entries"][0]["name"] == "Remote Rice"


def test_custom_food_used_by_another_user_is_hidden_only_for_the_creator(a, b):
    f = food(a, SALT)
    b.post(f"/api/favorites/{f['id']}")
    assert a.delete(f"/api/foods/{f['id']}").json()["everyone"] is False
    assert f["id"] not in search_ids(a, "mystery") and f["id"] in search_ids(b, "mystery")
    g = food(a, PB)  # nobody else uses it: hidden for everyone
    assert a.delete(f"/api/foods/{g['id']}").json()["everyone"] is True
    assert search_ids(b, "peanut") == []


def test_someone_elses_custom_food_can_be_hidden_for_me_only(a, b):
    f = food(a, SALT)
    assert b.delete(f"/api/foods/{f['id']}").json() == {"deleted": f["id"], "everyone": False}
    assert f["id"] in search_ids(a, "mystery") and f["id"] not in search_ids(b, "mystery")


def test_recent_meal_filter(a):
    bread, pb, salt = food(a), food(a, PB), food(a, SALT)
    log(a, bread, meal="breakfast")
    log(a, pb, meal="lunch")
    log(a, pb, meal="breakfast")
    log(a, salt)  # never logged with a meal: untagged, shows under every meal
    ids = lambda **q: [i["food"]["id"] for i in a.get("/api/quick/recent", params=q).json()["items"]]
    assert ids() == [salt["id"], pb["id"], bread["id"]] and ids(meal="all") == ids()
    assert ids(meal="breakfast") == [salt["id"], pb["id"], bread["id"]]
    assert ids(meal="lunch") == [salt["id"], pb["id"]]
    assert ids(meal="dinner") == [salt["id"]]
    assert a.get("/api/quick/recent", params={"meal": "brunch"}).status_code == 400
    items = {i["food"]["id"]: i for i in a.get("/api/quick/recent").json()["items"]}
    assert items[pb["id"]]["meals"] == ["breakfast", "lunch"] and items[pb["id"]]["counts"] == {"breakfast": 1, "lunch": 1}
    assert items[salt["id"]]["meals"] == []


def test_recent_meal_filter_applies_before_the_limit(a):
    old = food(a, SALT)
    log(a, old, meal="dinner")
    for i in range(25):
        log(a, food(a, {**BREAD, "name": f"Bread {i}"}), meal="breakfast")
    got = [i["food"]["id"] for i in a.get("/api/quick/recent", params={"meal": "dinner"}).json()["items"]]
    assert got == [old["id"]]


# ---------- #12: the picker starts on the package's own serving ----------

def test_food_route_and_quick_items_carry_the_package_serving(a):
    pb = food(a, PB)
    sv = food(a, {**BREAD, "name": "Cracker", "serving_amount": 1, "serving_unit": "serving", "serving_g": 30, "label_text": "1 serving (30 g)"})
    assert a.get(f"/api/foods/{pb['id']}").json()["default"] == {"amount": 2, "unit": "tbsp"}
    assert a.get(f"/api/foods/{sv['id']}").json()["default"] == {"amount": 30, "unit": "g"}
    assert "serving" in [u["unit"] for u in a.get(f"/api/foods/{sv['id']}").json()["units"]]
    a.post(f"/api/favorites/{sv['id']}")
    item = a.get("/api/quick/favorites").json()["items"][0]
    assert (item["amount"], item["unit"]) == (30, "g")
    log(a, sv, amount=2, unit="serving")  # a prior amount still wins (use last amount)
    item = a.get("/api/quick/favorites").json()["items"][0]
    assert (item["amount"], item["unit"]) == (2, "serving")
    assert a.get(f"/api/foods/{sv['id']}").json()["last"] == {"amount": 2, "unit": "serving"}
