"""Issue #45 steps 1 to 3: counts never become label servings, package and fuzzy units stay structured, printed sizes are exact."""
import sqlite3

import pytest

from app import core, db, ingredients, recipe_ai, units
from tests.test_recipe_ai import env, reply, saved_recipe  # noqa: F401

GARLIC_G = {"name": "Garlic, raw", "serving_amount": 100, "serving_unit": "g", "kcal": 149, "carbs": 33, "protein": 6.4, "fat": 0.5}
GARLIC_CLOVE = {"name": "Garlic", "serving_amount": 1, "serving_unit": "clove", "serving_g": 3, "kcal": 4.5, "carbs": 1, "protein": 0.2, "fat": 0}
BEANS = {"source": "fdc", "source_id": "b1", "name": "Black beans", "serving_amount": 100, "serving_unit": "g", "label_text": "100 g",
         "kcal": 91, "carbs": 16, "protein": 6, "fat": 0.3}
BEANS_CAN = {"name": "Black beans can", "serving_amount": 1, "serving_unit": "can", "serving_g": 425, "kcal": 380, "carbs": 68, "protein": 25, "fat": 1}
FLOUR_G = {"name": "All-purpose flour", "serving_amount": 30, "serving_unit": "g", "kcal": 110, "carbs": 23, "protein": 3, "fat": 0}
BAR = {"name": "Bar", "serving_amount": 1, "serving_unit": "serving", "serving_g": 40, "kcal": 200, "carbs": 20, "protein": 10, "fat": 8}


# ---------- step 1: a count on a measure label ----------

@pytest.mark.parametrize("amount,unit,want", [
    (2, "cloves", {"amount": 100, "unit": "g", "check": True, "reason": "no_weight"}),
    (2, None, {"amount": 100, "unit": "g", "check": True, "reason": "no_weight"}),
    (2, "count", {"amount": 100, "unit": "g", "check": True, "reason": "no_weight"}),
    (2, "piece", {"amount": 100, "unit": "g", "check": True, "reason": "no_weight"}),
    (1, "can", {"amount": 100, "unit": "g", "check": True, "reason": "no_size"}),
    (1, "Head", {"amount": 100, "unit": "g", "check": True, "reason": "no_weight"}),
    (2, "shell", {"amount": 100, "unit": "g", "check": True, "reason": "no_weight"}),
    (1, "cup", {"amount": 1, "unit": "cup", "check": False, "estimated": True}),
    (20, "g", {"amount": 20, "unit": "g", "check": False}),
])
def test_counts_on_a_gram_label_never_become_label_servings(amount, unit, want):
    assert units.match_amount(GARLIC_G, amount, unit) == want


def test_a_count_with_a_known_weight_converts_exactly():
    assert units.match_amount(GARLIC_CLOVE, 2, "cloves") == {"amount": 2, "unit": "clove", "check": False}
    assert units.match_amount(GARLIC_CLOVE, 2, None) == {"amount": 2, "unit": "clove", "check": False}
    assert units.grams(GARLIC_CLOVE, 2, "clove") == 6
    assert units.match_amount(GARLIC_CLOVE, 1, "head")["reason"] == "no_weight"  # another fuzzy unit: still no weight
    assert units.match_amount(BAR, 2, None)["check"] is True  # a serving label is a measure


def test_grams_never_reports_a_count_without_a_weight():
    for unit in ("count", "", "clove", "can", "shell", "piece"):
        assert units.grams(GARLIC_G, 2, unit) is None, unit
    assert units.grams(GARLIC_G, 50, "oz") is not None


def test_picker_offers_count_only_with_a_count_weight_and_server_still_accepts_counts():
    assert "count" not in [u["unit"] for u in units.available_units(GARLIC_G)]
    assert [u["unit"] for u in units.available_units(GARLIC_CLOVE)][-1] == "count"
    for unit in ("count", "", "clove", "can", "Shell"):  # older entries and typed words keep working
        assert core.check_amount_unit(GARLIC_G, 1, unit)[1] == units.unit_or_blank(unit)


# ---------- step 2: vocabulary ----------

@pytest.mark.parametrize("text,want", [
    ("cans", "can"), ("Jars", "jar"), ("bottles", "bottle"), ("bags", "bag"), ("boxes", "box"), ("packets", "packet"),
    ("packages", "package"), ("pkg", "package"), ("cartons", "carton"), ("sticks", "stick"), ("cloves", "clove"),
    ("slices", "slice"), ("bunches", "bunch"), ("heads", "head"), ("sprigs", "sprig"), ("pinches", "pinch"), ("dashes", "dash"),
    ("handfuls", "handful"), ("pieces", "piece"), ("fillets", "fillet"), ("ribs", "rib"), ("stalks", "stalk"), ("shells", "shell"),
])
def test_parse_unit_knows_package_and_fuzzy_units(text, want):
    assert units.parse_unit(text) == want
    assert units.is_countlike(want)


@pytest.mark.parametrize("unit,amount,want", [
    ("clove", 2, "cloves"), ("clove", 1, "clove"), ("clove", 0.5, "clove"), ("pinch", 3, "pinches"), ("box", 2, "boxes"),
    ("bunch", 2, "bunches"), ("dash", 2, "dashes"), ("can", 1.5, "cans"), ("cup", 2, "cup"), ("floz", 2, "fl oz"), ("Shell", 2, "Shell"),
])
def test_unit_word_plurals(unit, amount, want):
    assert units.unit_word(unit, amount) == want


def test_name_keys_and_search_strip_unit_words():
    assert ingredients.key("2 cloves garlic") == ingredients.key("garlic cloves") == ingredients.key("garlic") == "garlic"
    assert ingredients.key("1 (15 oz) can black beans") == ingredients.key("black beans")
    assert ingredients.key("2 boxes pasta") == "pasta"
    assert ingredients.core_words("garlic cloves") == {"garlic"} and ingredients.core_words("head") == {"head"}
    assert recipe_ai.name_score("garlic cloves", "Garlic")[0] == 2
    assert recipe_ai.name_score("pork ribs", "Pork ribs") > recipe_ai.name_score("pork ribs", "Pork loin")


def test_import_stores_structured_units_and_text(env):
    m = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [
        {"name": "garlic", "amount": 2, "unit": "Cloves"}, {"name": "salt", "amount": 1, "unit": "pinch"}, {"name": "x", "amount": 1, "unit": "shell"}]}).json()
    assert [(i["src"]["unit"], i["src"]["text"]) for i in m["items"]] == [("clove", "2 cloves garlic"), ("pinch", "1 pinch salt"), ("shell", "1 shell x")]


# ---------- step 3: printed sizes ----------

@pytest.mark.parametrize("text,want", [
    ("1 (15 oz) can black beans", (1, "can", 15, "oz", "black beans")),
    ("2 (8-ounce) packages cream cheese", (2, "package", 8, "oz", "cream cheese")),
    ("1 stick (113 g) butter", (1, "stick", 113, "g", "butter")),
    ("1 can (14.5 oz) diced tomatoes", (1, "can", 14.5, "oz", "diced tomatoes")),
    ("1 15-oz can chickpeas", (1, "can", 15, "oz", "chickpeas")),
    ("2 (12 fl oz) bottles beer", (2, "bottle", 12, "floz", "beer")),
    ("1 1/2 (1 lb) bags spinach", (1.5, "bag", 1, "lb", "spinach")),
    ("1 (400 ml) carton stock", (1, "carton", 400, "ml", "stock")),
])
def test_printed_size(text, want):
    p = units.printed_size(text)
    assert (p["amount"], p["unit"], p["size"], p["size_unit"], p["rest"]) == want


@pytest.mark.parametrize("text", ["1 (14 to 15 oz) can beans", "1 (14-15 oz) can beans", "1 (oz) can beans", "1 (15 bananas) can",
                                  "2 cans beans", "1 cup (240 ml) milk", "salt to taste", "", None])
def test_printed_size_falls_back(text):
    assert units.printed_size(text) is None


def test_match_amount_uses_the_printed_size_once():
    assert units.match_amount(BEANS, 1, "can", pkg=(15, "oz")) == {"amount": 15, "unit": "oz", "check": False}
    assert units.match_amount(BEANS, 2, "package", pkg=(8, "oz")) == {"amount": 16, "unit": "oz", "check": False}
    assert units.grams(BEANS, 15, "oz") == 425.2
    # a food labelled per can: the printed size wins, never can x printed size
    assert units.match_amount(BEANS_CAN, 1, "can", pkg=(15, "oz")) == {"amount": 15, "unit": "oz", "check": False}
    assert units.match_amount(BEANS, 1, "can", pkg=(None, None))["reason"] == "no_size"
    no_weight = {"serving_amount": 2, "serving_unit": "slice"}
    assert units.match_amount(no_weight, 1, "can", pkg=(15, "oz"))["reason"] == "no_convert"
    assert units.match_amount(BEANS, 1, "cup", pkg=(15, "oz"))["unit"] == "cup"  # a measure line ignores a stray size


def test_clean_recipe_reads_printed_sizes():
    draft, _ = recipe_ai.clean_recipe({"name": "C", "ingredients": [
        {"text": "1 (15 oz) can black beans, rinsed", "amount": 15, "unit": "oz", "name": "black beans", "note": "rinsed"},
        {"text": "1 stick (113 g) butter", "amount": 1, "unit": "stick", "name": "butter", "note": "113 g"},
        {"text": "1 (14 to 15 oz) can tomatoes", "amount": 1, "unit": "can", "name": "tomatoes", "note": None}]})
    got = [(i["amount"], i["unit"], i["name"], i["note"], i["pkg_amount"], i["pkg_unit"]) for i in draft["ingredients"]]
    assert got == [(1, "can", "black beans", "15 oz, rinsed", 15, "oz"), (1, "stick", "butter", "113 g", 113, "g"),
                   (1, "can", "tomatoes", None, None, None)]


def test_import_keeps_the_printed_size_and_search_logs_exact_grams(env):
    env["fdc"]["black beans"] = [BEANS]
    env["fdc"]["tomatoes"] = [{**BEANS, "source_id": "t1", "name": "Tomatoes"}]
    m = saved_recipe(env, [{"text": "1 (15 oz) can black beans", "amount": 1, "unit": "can", "name": "black beans", "pkg_amount": 15, "pkg_unit": "oz"},
                           {"text": "1 can (14.5 oz) tomatoes", "amount": 1, "unit": "can", "name": "tomatoes"},
                           {"text": "1 can tomatoes", "amount": 1, "unit": "can", "name": "tomatoes"}])
    assert [(i["src"]["pkg_amount"], i["src"]["pkg_unit"]) for i in m["items"]] == [(15, "oz"), (14.5, "oz"), (None, None)]
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [i["id"] for i in m["items"]]}).json()["proposals"]
    assert [(x["amount"], x["unit"], x["check"], x["grams"], x["check_reason"]) for x in p] == [
        (15, "oz", False, 425.2, None), (14.5, "oz", False, 411.1, None), (100, "g", True, None, "no_size")]
    assert p[2]["warnings"] == [recipe_ai.NO_SIZE_WARNING]


@pytest.mark.parametrize("bad", [{"pkg_amount": 0, "pkg_unit": "oz"}, {"pkg_amount": 15, "pkg_unit": "can"}, {"pkg_amount": 15},
                                 {"pkg_amount": "x", "pkg_unit": "oz"}, {"pkg_amount": 1e9, "pkg_unit": "g"}])
def test_import_validates_the_printed_size(env, bad):
    r = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [{"name": "beans", "amount": 1, "unit": "can", **bad}]})
    assert r.status_code == 400


def test_a_printed_size_needs_a_count_like_unit_and_an_amount(env):
    m = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [
        {"name": "beans", "amount": 2, "unit": "cup", "pkg_amount": 15, "pkg_unit": "oz"},
        {"name": "beans", "unit": "can", "pkg_amount": 15, "pkg_unit": "ounces"},
        {"name": "beans", "amount": 1, "unit": "can", "pkg_amount": 15, "pkg_unit": "ounces"}]}).json()
    assert [(i["src"]["pkg_amount"], i["src"]["pkg_unit"]) for i in m["items"]] == [(None, None), (None, None), (15, "oz")]


def test_duplicate_copies_the_printed_size(env):
    m = saved_recipe(env, [{"text": "1 (15 oz) can black beans", "amount": 1, "unit": "can", "name": "black beans"}])
    copy = env["c"].post(f"/api/meals/{m['id']}/duplicate", json={}).json()
    assert (copy["items"][0]["src"]["pkg_amount"], copy["items"][0]["src"]["pkg_unit"]) == (15, "oz")


def test_migration_adds_the_printed_size_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE meal_items(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL, food_id INTEGER, amount REAL, unit TEXT, "
                  "position INTEGER NOT NULL DEFAULT 0, src_text TEXT, src_amount REAL, src_unit TEXT, src_name TEXT, src_note TEXT, "
                  "skipped INTEGER NOT NULL DEFAULT 0, needs_check INTEGER NOT NULL DEFAULT 0)")
        c.execute("INSERT INTO meal_items(meal_id, src_text, src_name) VALUES (1, '1 can beans', 'beans')")
    monkeypatch.setenv("DB_PATH", str(path))
    for _ in range(2):  # safe to run again
        with db.conn() as c:
            db.init_shared(c)
            core.init(c)
    with db.conn() as c:
        row = c.execute("SELECT src_text, item_pkg_amount, item_pkg_unit FROM meal_items").fetchone()
    assert tuple(row) == ("1 can beans", None, None)


# ---------- the reason a row needs a check ----------

def test_each_check_row_says_why(env):
    g = env["c"].post("/api/foods", json=GARLIC_G).json()
    slice_only = env["c"].post("/api/foods", json={"name": "Bread", "serving_amount": 1, "serving_unit": "slice", "kcal": 80, "carbs": 15,
                                                   "protein": 3, "fat": 1}).json()
    m = saved_recipe(env, [{"amount": 2, "unit": "clove", "name": "garlic"}, {"amount": 1, "unit": "can", "name": "garlic"},
                           {"amount": 1, "unit": "cup", "name": "bread"}, {"name": "garlic", "note": "for serving"},
                           {"amount": 1, "unit": "cup", "name": "garlic"}])
    ids = [i["id"] for i in m["items"]]
    body = [{"id": ids[0], "food_id": g["id"], "amount": 100, "unit": "g", "check": True},
            {"id": ids[1], "food_id": g["id"], "amount": 100, "unit": "g", "check": True},
            {"id": ids[2], "food_id": slice_only["id"], "amount": 1, "unit": "slice", "check": True},
            {"id": ids[3], "food_id": g["id"], "amount": 100, "unit": "g", "check": True},
            {"id": ids[4], "food_id": g["id"], "amount": 1, "unit": "cup"}]
    r = env["c"].patch(f"/api/meals/{m['id']}/items", json={"items": body}).json()
    assert [i["check_reason"] for i in r["items"]] == ["no_weight", "no_size", "no_convert", "no_amount", None]
    assert [i["grams"] for i in r["items"][:4]] == [None] * 4  # a Check Amount row never shows a weight as exact
    assert (r["checks"], r["matched"]) == (4, 1) and r["kcal"] == pytest.approx(r["items"][4]["kcal"], abs=0.05)  # check rows count for nothing
    assert r["items"][4]["estimated"] is True and r["items"][4]["estimate_source"] == "guess"
    assert units.estimate_source(FLOUR_G) == "density"


def test_claude_weight_for_a_line_with_none_is_tagged_estimated(env):
    m = saved_recipe(env, [{"text": "2 cloves garlic", "amount": 2, "unit": "clove", "name": "flour"}])
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [{"row": 1, "choice": 1, "amount": 6, "unit": "g", "estimate": None, "note": None}]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"][0]
    assert (p["amount"], p["unit"], p["check"], p["estimated"], p["estimate_source"]) == (6, "g", False, True, "claude")
    assert p["warnings"] == [recipe_ai.ESTIMATED_WEIGHT_WARNING]
