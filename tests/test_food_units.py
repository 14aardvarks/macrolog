"""Issue #45 steps 4 to 6: food_units (user, printed size, fdc and off, table, ai), typical piece weights, standard package sizes,
the wider density table, USDA portions and Open Food Facts quantities."""
import sqlite3

import httpx
import pytest

from app import core, db, lookup, units
from tests.test_recipe_ai import env, saved_recipe  # noqa: F401

CUP = units.VOLUME["cup"]


def food(name, amount=100, unit="g", **kw):
    return {"name": name, "serving_amount": amount, "serving_unit": unit, "kcal": 100, "carbs": 10, "protein": 5, "fat": 1, **kw}


def table(name):
    return {r["unit"]: r["grams"] for r in units.table_weights(food(name))}


# ---------- step 5: typical piece weights ----------

@pytest.mark.parametrize("name,unit,grams", [
    ("Garlic, raw", "clove", 3), ("Garlic", "head", 40),
    ("Egg, whole, raw, fresh", "count", 50), ("Eggs", "large", 50), ("Eggs", "medium", 44), ("Eggs", "small", 38),
    ("Egg white", "count", 33), ("Egg yolk", "count", 17),
    ("Onions, raw", "medium", 110), ("Onion", "small", 70), ("Onion", "large", 150), ("Onion", "count", 110),
    ("Green onions", "count", 15), ("Scallions", "bunch", 100),
    ("Butter, salted", "stick", 113), ("Celery, raw", "rib", 40), ("Celery", "stalk", 40),
    ("Thyme, fresh", "sprig", 1), ("Rosemary", "sprig", 1), ("Bread, whole wheat", "slice", 28), ("Cheddar cheese", "slice", 21),
    ("Salt, table", "pinch", 0.36), ("Black pepper", "dash", 0.6), ("Almonds", "handful", 30), ("Baby spinach", "handful", 25),
    ("Lettuce, iceberg", "head", 539), ("Romaine lettuce", "head", 626), ("Cabbage", "head", 908), ("Cauliflower", "head", 588),
    ("Broccoli", "head", 608), ("Potatoes, russet", "medium", 170), ("Sweet potato", "count", 130),
    ("Carrots, raw", "medium", 61), ("Carrot", "large", 72), ("Lemons, raw", "count", 58), ("Limes", "count", 67),
    ("Tomatoes, red, ripe, raw", "medium", 123), ("Cherry tomatoes", "count", 17), ("Peppers, sweet, red, raw", "medium", 120),
    ("Red bell pepper", "large", 164), ("Bananas, raw", "medium", 118), ("Apples, raw, with skin", "medium", 182),
    ("Oranges", "count", 131), ("Avocado", "count", 150), ("Zucchini", "count", 196), ("Mushrooms, white", "count", 18),
    ("Strawberries", "count", 12), ("Bay leaf", "count", 0.2), ("Chicken breast, boneless", "fillet", 174),
    ("Salmon, Atlantic", "fillet", 170), ("Cilantro", "bunch", 60), ("Parsley, fresh", "bunch", 60), ("Kale", "bunch", 200),
    ("Spinach, raw", "bunch", 340),
])
def test_piece_weight_rows(name, unit, grams):
    assert table(name)[unit] == grams


@pytest.mark.parametrize("name,unit", [
    ("Garlic powder", "clove"), ("Egg noodles", "count"), ("Eggplant", "count"), ("Onion powder", "medium"), ("Green onions", "medium"),
    ("Peanut butter", "stick"), ("Celery salt", "rib"), ("Dried thyme", "sprig"), ("Bread crumbs", "slice"), ("Cream cheese", "slice"),
    ("Chicken thighs", "pinch"), ("Tomato paste", "medium"), ("Apple juice", "count"), ("Banana chips", "count"),
    ("Lemon juice", "count"), ("Sweet potato fries", "count"), ("Potato chips", "medium"), ("Chicken nuggets", "fillet"),
    ("Mystery root", "count"),
])
def test_piece_weight_exclusions(name, unit):
    assert unit not in table(name)


# ---------- step 5: standard package sizes ----------

@pytest.mark.parametrize("name,unit,grams", [
    ("Black beans", "can", 425), ("Beans, kidney, canned", "can", 425), ("Chickpeas", "can", 425), ("Diced tomatoes", "can", 411),
    ("Tomatoes, canned, diced", "can", 411), ("Tomato paste", "can", 170), ("Cream cheese", "package", 227),
    ("Condensed cream of mushroom soup", "can", 298), ("Frozen mixed vegetables", "bag", 340), ("Peas, frozen", "bag", 340),
    ("Spaghetti, dry", "box", 454), ("Penne pasta", "package", 454), ("Green beans", "can", 411), ("Chicken broth", "carton", 946),
])
def test_standard_package_rows(name, unit, grams):
    row = next(r for r in units.table_weights(food(name)) if r["unit"] == unit)
    assert row["grams"] == grams and row["source"] == "table" and row["estimated"] is True
    assert row["note"] == f"Standard {unit} size assumed"


@pytest.mark.parametrize("name,unit", [("Coffee beans", "can"), ("Jelly beans", "can"), ("Pasta sauce", "box"), ("Cooked pasta", "box"),
                                       ("Tomatoes", "can"), ("Soup mix", "can"), ("Mystery mash", "can")])
def test_standard_package_exclusions(name, unit):
    assert unit not in table(name)


def test_can_note_text():
    assert units.package_note("can") == "Standard can size assumed"


# ---------- step 5: wider density table ----------

@pytest.mark.parametrize("name,cup", [
    ("Onions, chopped", 160), ("Red bell pepper", 150), ("Carrots", 128), ("Celery", 101), ("Shredded cheddar", 113),
    ("Mozzarella, shredded", 112), ("Almonds", 143), ("Walnuts", 117), ("Black beans, cooked", 172), ("Chickpeas", 164),
    ("Chicken broth", 240), ("Peas, frozen", 134), ("Spinach, raw", 30), ("Spinach, cooked", 180), ("Brown sugar", 213),
    ("Honey", 340), ("Ground cumin", 101), ("Cinnamon, ground", 125), ("Garlic powder", 149), ("Onion powder", 115),
    ("Soy sauce", 255), ("Rice, cooked", 158), ("Garlic, minced", 136), ("Tomato paste", 262), ("Diced tomatoes", 240),
])
def test_density_rows(name, cup):
    assert units.density(food(name)) == pytest.approx(cup / CUP)


@pytest.mark.parametrize("name,not_cup", [("Onion powder", 160), ("Peanut butter", 146), ("Garlic powder", 136), ("Black pepper", 150),
                                          ("Green beans", 172), ("Sugar snap peas", 134), ("Coffee beans", 172)])
def test_density_exclusions(name, not_cup):
    d = units.density(food(name))
    assert d is None or d != pytest.approx(not_cup / CUP)


# ---------- step 4: resolution and trust order ----------

GARLIC = food("Garlic, raw", kcal=149)


def test_cloves_of_a_gram_label_convert_through_the_table_as_an_estimate():
    assert units.match_amount(GARLIC, 2, "cloves") == {"amount": 2, "unit": "clove", "check": False, "estimated": True, "source": "table"}
    assert units.servings_for(GARLIC, 2, "clove") == {"servings": pytest.approx(0.06), "estimated": True}
    assert units.grams(GARLIC, 2, "clove") is None  # an estimate is never shown as exact grams
    assert units.estimate_source(GARLIC, "clove") == "table"
    clove = next(u for u in units.available_units(GARLIC) if u["unit"] == "clove")
    assert (clove["label"], clove["grams"], clove["estimated"], clove["source"]) == ("clove (3 g)", 3, True, "table")


def test_plain_counts_use_the_size_the_line_names():
    egg = food("Egg, whole, raw")
    assert units.match_amount(egg, 2, None)["unit"] == "count"
    assert units.match_amount(egg, 2, None, hint="large eggs")["unit"] == "large"
    assert units.match_amount(egg, 2, "count", hint="small eggs")["unit"] == "small"
    assert units.match_amount(egg, 2, None, hint="extra-large eggs")["unit"] == "large"
    assert units.servings_for(egg, 2, "medium")["servings"] == pytest.approx(0.88)
    assert units.match_amount(egg, 2, "shell", custom=False)["unit"] == "count"  # a typed word counts as a plain count


def test_a_count_word_label_still_wins():
    egg = food("Egg", 1, "egg", serving_g=50)
    assert units.match_amount(egg, 2, None, hint="small eggs") == {"amount": 2, "unit": "egg", "check": False}
    assert "medium" not in [u["unit"] for u in units.available_units(egg)]


def rows(*specs):
    return [{"unit": u, "grams": g, "source": s, "estimated": s in ("table", "ai")} for u, g, s in specs]


def test_trust_order_user_then_source_then_table_then_ai():
    f = {**GARLIC, "food_units": rows(("clove", 9, "ai"), ("clove", 4, "fdc"))}
    assert units.unit_weights(f)["clove"]["source"] == "fdc"
    assert units.match_amount(f, 2, "clove") == {"amount": 2, "unit": "clove", "check": False, "source": "fdc"}
    assert units.grams(f, 2, "clove") == 8  # exact
    f["food_units"] += rows(("clove", 5, "user"))
    assert units.grams(f, 2, "clove") == 10
    ai_only = {**food("Mystery root"), "food_units": rows(("clove", 9, "ai"))}
    assert units.match_amount(ai_only, 1, "clove")["source"] == "ai"
    table_vs_ai = {**GARLIC, "food_units": rows(("clove", 9, "ai"))}
    assert units.unit_weights(table_vs_ai)["clove"]["source"] == "table"


def test_only_a_user_weight_beats_a_printed_size():
    beans = food("Black beans")
    assert units.match_amount(beans, 1, "can", pkg=(15, "oz"))["unit"] == "oz"
    beans["food_units"] = rows(("can", 425, "fdc"))
    assert units.match_amount(beans, 1, "can", pkg=(15, "oz"))["unit"] == "oz"
    beans["food_units"] = rows(("can", 400, "user"))
    assert units.match_amount(beans, 1, "can", pkg=(15, "oz")) == {"amount": 1, "unit": "can", "check": False, "source": "user"}


def test_a_volume_row_gives_an_exact_density():
    f = {**food("Mystery root"), "food_units": rows(("cup", 150, "fdc"))}
    assert units.servings_for(f, 1, "cup") == {"servings": pytest.approx(1.5), "estimated": False}
    assert units.grams(f, 1, "cup") == 150
    est = {**food("Mystery root"), "food_units": rows(("cup", 150, "ai"))}
    assert units.servings_for(est, 1, "cup")["estimated"] is True and units.estimate_source(est) == "ai"


def test_no_weight_anywhere_still_asks_for_a_check():
    assert units.match_amount(food("Mystery root"), 2, "clove")["reason"] == "no_weight"
    assert units.match_amount(food("Mystery root"), 1, "can")["reason"] == "no_size"
    no_grams = food("Garlic", 1, "cup")  # a volume label with no grams still reaches grams through the density
    assert units.match_amount(no_grams, 2, "clove")["estimated"] is True


@pytest.mark.parametrize("text,want", [("Cloves", "clove"), ("large", "large"), ("each", "count"), ("Cups", "cup"), ("fl oz", "floz"),
                                       ("g", None), ("serving", None), ("shell", None)])
def test_weight_unit(text, want):
    assert units.weight_unit(text) == want


# ---------- step 4: table, routes and saving typed grams ----------

def test_migration_is_safe_to_run_again(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "m.db"))
    for _ in range(2):
        with db.conn() as c:
            db.init_shared(c)
            core.init(c)
    with db.conn() as c:
        assert {r[1] for r in c.execute("PRAGMA table_info(food_units)")} >= {"food_id", "user_id", "unit", "grams", "source", "estimated", "created_at"}
        assert {"item_was_amount", "item_was_unit"} <= {r[1] for r in c.execute("PRAGMA table_info(meal_items)")}
        assert "portions_at" in {r[1] for r in c.execute("PRAGMA table_info(foods)")}


def test_unique_per_food_user_unit_source(env):
    f = env["c"].post("/api/foods", json=food("Mystery root")).json()
    with db.conn() as c:
        for g in (3, 4):
            core.save_unit_weight(c, f["id"], None, "clove", g, "fdc")
            core.save_unit_weight(c, f["id"], 1, "clove", g + 1, "user")
        assert not core.save_unit_weight(c, f["id"], None, "clove", 9, "ai")  # ai is never global
        assert not core.save_unit_weight(c, f["id"], 1, "g", 9, "user")
        got = sorted(tuple(r) for r in c.execute("SELECT unit, grams, source, user_id FROM food_units"))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO food_units(food_id, user_id, unit, grams, source, created_at) VALUES(?,NULL,'clove',1,'fdc','x')", (f["id"],))
    assert got == [("clove", 4, "fdc", None), ("clove", 5, "user", 1)]


def test_routes_show_set_and_delete_the_viewers_own_weight(env):
    f = env["c"].post("/api/foods", json=food("Garlic, raw")).json()
    r = env["c"].get(f"/api/foods/{f['id']}/units").json()
    assert {(u["unit"], u["source"]) for u in r["units"]} >= {("clove", "table"), ("head", "table")}
    r = env["c"].put(f"/api/foods/{f['id']}/units", json={"unit": "Cloves", "grams": 5}).json()
    clove = next(u for u in r["units"] if u["unit"] == "clove")
    assert (clove["grams"], clove["source"], clove["estimated"], clove["label"]) == (5, "user", False, "clove (5 g)")
    # the other user sees the table weight, never mine, and no Claude row of mine either
    with db.conn() as c:
        core.save_unit_weight(c, f["id"], 1, "head", 50, "ai", True)
    theirs = env["b"].get(f"/api/foods/{f['id']}/units").json()
    assert {(u["unit"], u["source"]) for u in theirs["units"] if u["unit"] in ("clove", "head")} == {("clove", "table"), ("head", "table")}
    picker = {u["unit"]: u for u in env["c"].get(f"/api/foods/{f['id']}").json()["units"]}
    assert picker["clove"]["label"] == "clove (5 g)" and picker["clove"]["estimated"] is False
    assert env["c"].delete(f"/api/foods/{f['id']}/units/clove").status_code == 200
    assert next(u for u in env["c"].get(f"/api/foods/{f['id']}/units").json()["units"] if u["unit"] == "clove")["source"] == "table"
    assert env["c"].delete(f"/api/foods/{f['id']}/units/clove").status_code == 200  # fine when there is none


@pytest.mark.parametrize("body", [{"unit": "g", "grams": 5}, {"unit": "clove"}, {"unit": "clove", "grams": 0}, {"unit": "clove", "grams": 1e9},
                                  {"unit": "clove", "grams": 3, "x": 1}, {"unit": 5, "grams": 3}, {"unit": "clove", "grams": "x"}])
def test_put_validation(env, body):
    f = env["c"].post("/api/foods", json=food("Garlic")).json()
    assert env["c"].put(f"/api/foods/{f['id']}/units", json=body).status_code == 400


def test_unknown_food_is_404(env):
    assert env["c"].get("/api/foods/999/units").status_code == 404
    assert env["c"].put("/api/foods/999/units", json={"unit": "clove", "grams": 3}).status_code == 404


def test_recipe_rows_carry_the_weight_source_and_note(env):
    beans = env["c"].post("/api/foods", json=food("Black beans")).json()
    garlic = env["c"].post("/api/foods", json=food("Garlic, raw")).json()
    m = saved_recipe(env, [{"text": "1 can black beans", "amount": 1, "unit": "can", "name": "black beans"},
                           {"text": "2 cloves garlic", "amount": 2, "unit": "clove", "name": "garlic"}])
    ids = [i["id"] for i in m["items"]]
    r = env["c"].patch(f"/api/meals/{m['id']}/items", json={"items": [
        {"id": ids[0], "food_id": beans["id"], "amount": 1, "unit": "can"},
        {"id": ids[1], "food_id": garlic["id"], "amount": 2, "unit": "clove"}]}).json()
    a, b = r["items"]
    assert (a["estimated"], a["estimate_source"], a["weight_source"], a["weight_note"]) == (True, "table", "table", "Standard can size assumed")
    assert a["kcal"] == pytest.approx(425) and a["grams"] is None
    assert (b["estimated"], b["estimate_source"], b["weight_source"]) == (True, "table", "table")


def test_match_search_resolves_cloves_and_cans_with_an_estimate(env):
    env["fdc"]["garlic"] = [{**food("Garlic, raw"), "source": "fdc", "source_id": "g1", "label_text": "100 g"}]
    m = saved_recipe(env, [{"text": "3 cloves garlic", "amount": 3, "unit": "clove", "name": "garlic"},
                           {"text": "2 large eggs", "amount": 2, "unit": "count", "name": "large eggs"}])
    env["fdc"]["large eggs"] = [{**food("Egg, whole, raw"), "source": "fdc", "source_id": "e9", "label_text": "100 g"}]
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [i["id"] for i in m["items"]]}).json()["proposals"]
    assert [(x["amount"], x["unit"], x["check"], x["estimated"], x["estimate_source"], x["weight_source"]) for x in p] == [
        (3, "clove", False, True, "table", "table"), (2, "large", False, True, "table", "table")]


def test_enter_grams_saves_the_users_weight_for_the_next_line(env):
    root = env["c"].post("/api/foods", json=food("Mystery root")).json()
    m = saved_recipe(env, [{"text": "2 cloves mystery root", "amount": 2, "unit": "clove", "name": "mystery root"},
                           {"text": "4 cloves mystery root", "amount": 4, "unit": "clove", "name": "mystery root"}])
    i1, i2 = [i["id"] for i in m["items"]]
    base = f"/api/meals/{m['id']}/items/"
    env["c"].patch(base + str(i1), json={"food_id": root["id"], "amount": 100, "unit": "g", "check": True})
    env["c"].patch(base + str(i1), json={"food_id": root["id"], "amount": 8, "unit": "g"})  # no remember: nothing saved
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM food_units").fetchone()[0] == 0
    env["c"].patch(base + str(i1), json={"food_id": root["id"], "amount": 8, "unit": "g", "remember": True})
    units_ = env["c"].get(f"/api/foods/{root['id']}/units").json()["units"]
    assert [(u["unit"], u["grams"], u["source"]) for u in units_] == [("clove", 4, "user")]
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [i2]}).json()["proposals"][0]
    assert (p["amount"], p["unit"], p["check"], p["grams"], p.get("estimated"), p["weight_source"]) == (4, "clove", False, 16, False, "user")
    # the other user does not get my weight
    assert env["b"].get(f"/api/foods/{root['id']}/units").json()["units"] == []
    assert env["c"].patch(base + str(i1), json={"food_id": root["id"], "amount": 8, "unit": "g", "remember": "yes"}).status_code == 400


def test_use_grams_keeps_the_line_and_saves_the_weight_once_matched(env):
    root = env["c"].post("/api/foods", json=food("Mystery root")).json()
    m = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [
        {"text": "9 g mystery root", "amount": 9, "unit": "g", "name": "mystery root", "was_amount": 3, "was_unit": "Cloves"},
        {"text": "2 cloves mystery root", "amount": 2, "unit": "clove", "name": "mystery root"}]}).json()
    i1, i2 = [i["id"] for i in m["items"]]
    env["c"].patch(f"/api/meals/{m['id']}/items/{i1}", json={"food_id": root["id"], "amount": 9, "unit": "g"})
    units_ = env["c"].get(f"/api/foods/{root['id']}/units").json()["units"]
    assert [(u["unit"], u["grams"], u["source"]) for u in units_] == [("clove", 3, "user")]
    copy = env["c"].post(f"/api/meals/{m['id']}/duplicate", json={}).json()
    assert copy["items"][1]["src"]["unit"] == "clove"
    with db.conn() as c:
        assert c.execute("SELECT item_was_amount, item_was_unit FROM meal_items WHERE meal_id=? ORDER BY position", (copy["id"],)).fetchone()[:] == (3, "clove")


@pytest.mark.parametrize("bad", [{"was_amount": 0, "was_unit": "clove"}, {"was_amount": 2}, {"was_amount": 2, "was_unit": "cup"},
                                 {"was_amount": 1e9, "was_unit": "clove"}])
def test_use_grams_validation(env, bad):
    r = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [{"name": "garlic", "amount": 9, "unit": "g", **bad}]})
    assert r.status_code == 400


def test_was_is_dropped_when_the_line_is_not_a_weight(env):
    m = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [
        {"name": "garlic", "amount": 2, "unit": "clove", "was_amount": 2, "was_unit": "clove"}]}).json()
    with db.conn() as c:
        assert tuple(c.execute("SELECT item_was_amount, item_was_unit FROM meal_items WHERE meal_id=?", (m["id"],)).fetchone()) == (None, None)


# ---------- step 6: USDA portions and Open Food Facts quantities ----------

FDC_DETAIL = {"fdcId": 1104647, "description": "Garlic, raw", "foodNutrients": [], "foodPortions": [
    {"amount": 1, "modifier": "clove", "gramWeight": 3, "measureUnit": {"name": "undetermined"}},
    {"amount": 1, "modifier": "tsp", "gramWeight": 2.8, "measureUnit": {"name": "undetermined"}},
    {"amount": 1, "modifier": "cup", "gramWeight": 136, "measureUnit": {"name": "undetermined"}},
    {"amount": 3, "modifier": "oz", "gramWeight": 85, "measureUnit": {"name": "undetermined"}},
    {"amount": 1, "modifier": "NLEA serving", "gramWeight": 85},
    {"portionDescription": "2 head", "gramWeight": 80}]}


def test_fdc_portions_map_known_units_and_ignore_the_rest():
    assert lookup.fdc_portions(FDC_DETAIL) == [{"unit": "clove", "grams": 3}, {"unit": "tsp", "grams": 2.8}, {"unit": "cup", "grams": 136},
                                               {"unit": "head", "grams": 40}]
    onion = {"foodPortions": [{"amount": 1, "modifier": "cup, sliced", "gramWeight": 115}, {"amount": 1, "modifier": "cup, chopped", "gramWeight": 160},
                              {"amount": 1, "modifier": "medium (2-1/2\" dia)", "gramWeight": 110}, {"amount": 1, "modifier": "large (3\" dia)", "gramWeight": 150},
                              {"amount": 1, "modifier": "extra large", "gramWeight": 200}, {"amount": 1, "gramWeight": 0, "modifier": "small"}]}
    assert lookup.fdc_portions(onion) == [{"unit": "cup", "grams": 160}, {"unit": "medium", "grams": 110}, {"unit": "large", "grams": 150}]


@pytest.mark.parametrize("p,want", [
    ({"product_quantity": 425, "packaging": "Can, metal"}, [("can", 425), ("package", 425)]),
    ({"product_quantity": "340", "packaging_tags": ["en:plastic-bag"]}, [("bag", 340), ("package", 340)]),
    ({"product_quantity": "340", "packaging": "Plastic"}, [("package", 340)]),
    ({"product_quantity": 500, "packaging_tags": ["en:bag"]}, [("bag", 500), ("package", 500)]),
    ({"quantity": "15 oz"}, [("package", 425.2)]),
    ({"product_quantity": 1, "product_quantity_unit": "l"}, []),
    ({"product_quantity": 20, "serving_quantity": 30}, []),
    ({}, []),
])
def test_off_portions(p, want):
    assert [(r["unit"], r["grams"]) for r in lookup.off_portions(p)] == want


def fdc_saved(source_id="1104647"):
    with db.conn() as c:
        return core.save_food(c, core.normalize_food({**food("Garlic, raw"), "source": "fdc", "source_id": source_id}))


def test_picking_an_fdc_food_reads_its_portions_once(env, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=FDC_DETAIL)
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(handler))
    f = fdc_saved()
    with db.conn() as c:
        core.save_unit_weight(c, f["id"], 1, "clove", 5, "user")
    picker = {u["unit"]: u for u in env["c"].get(f"/api/foods/{f['id']}").json()["units"]}
    assert seen == ["/fdc/v1/food/1104647"]
    assert picker["clove"]["source"] == "user" and picker["head"]["source"] == "fdc" and picker["head"]["estimated"] is False
    theirs = {u["unit"]: u for u in env["b"].get(f"/api/foods/{f['id']}").json()["units"]}
    assert (theirs["clove"]["grams"], theirs["clove"]["source"]) == (3, "fdc")
    assert seen == ["/fdc/v1/food/1104647"]  # read once for everyone
    with db.conn() as c:  # the user row was never overwritten
        assert c.execute("SELECT grams FROM food_units WHERE user_id=1").fetchone()[0] == 5


def test_portions_fail_soft_and_try_again_later(env, monkeypatch):
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(lambda r: httpx.Response(429, json={})))
    f = fdc_saved()
    r = env["c"].get(f"/api/foods/{f['id']}")
    assert r.status_code == 200 and "clove" in [u["unit"] for u in r.json()["units"]]  # the table still answers
    with db.conn() as c:
        assert c.execute("SELECT portions_at FROM foods WHERE id=?", (f["id"],)).fetchone()[0] is None
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json=FDC_DETAIL)))
    env["c"].get(f"/api/foods/{f['id']}")
    assert env["c"].get(f"/api/foods/{f['id']}/units").json()["units"][0]["source"] == "fdc"


def test_search_saves_off_package_sizes(env, monkeypatch):
    off = lookup.off_food("123", {"code": "123", "product_name": "Black beans", "nutriments": {"energy-kcal_100g": 91, "carbohydrates_100g": 16,
                                                                                              "proteins_100g": 6, "fat_100g": 0.3},
                                  "product_quantity": 439, "packaging": "Can"})
    assert off["portions"] == [{"unit": "can", "grams": 439}, {"unit": "package", "grams": 439}]
    env["off"]["black beans"] = [off]
    found = env["c"].get("/api/foods/search", params={"q": "black beans"}).json()["results"]
    units_ = {u["unit"]: u for u in env["c"].get(f"/api/foods/{found[0]['id']}/units").json()["units"]}
    assert (units_["can"]["grams"], units_["can"]["source"]) == (439, "off")  # beats the standard 425 g can


def test_refresh_backfills_fdc_portions(env, monkeypatch):
    detail = {**FDC_DETAIL, "foodNutrients": [{"nutrient": {"id": 1008, "number": "208", "unitName": "kcal"}, "amount": 149},
                                              {"nutrient": {"id": 1005, "number": "205", "unitName": "g"}, "amount": 33},
                                              {"nutrient": {"id": 1003, "number": "203", "unitName": "g"}, "amount": 6.4},
                                              {"nutrient": {"id": 1004, "number": "204", "unitName": "g"}, "amount": 0.5}]}
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json=detail)))
    f = fdc_saved()
    with db.conn() as c:
        c.execute("UPDATE foods SET portions_at='2020-01-01' WHERE id=?", (f["id"],))  # read before, rows since lost
    r = env["c"].post(f"/api/foods/{f['id']}/refresh-nutrients")
    assert r.status_code == 200, r.text
    assert {u["unit"] for u in env["c"].get(f"/api/foods/{f['id']}/units").json()["units"] if u["source"] == "fdc"} == {"clove", "tsp", "cup", "head"}
