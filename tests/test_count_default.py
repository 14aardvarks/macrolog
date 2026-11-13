"""Issue #44: an amount with no unit is a count, Claude and Search never produce a custom unit, and a to taste line has no amount."""
import pytest

from app import recipe_ai, units
from tests.test_recipe_ai import EGG_OFF, FLOUR, JPEG, env, reply, saved_recipe  # noqa: F401
from tests import test_recipe_url as url_tests

CASES = [  # (amount, unit text) -> (unit, name) for the name "garlic"
    (3, None, "count", "garlic"), (3, "", "count", "garlic"), (3, "none", "count", "garlic"), (3, "count", "count", "garlic"),
    (3, "Cups", "cup", "garlic"), (2, "tablespoons", "tbsp", "garlic"), (1, "fl oz", "floz", "garlic"), (1, "grams", "g", "garlic"),
    (2, "clove", "clove", "garlic"), (2, "cloves", "clove", "garlic"), (1, "Cloves", "clove", "garlic"),  # issue #45: never folded
    (2, "pinches", "pinch", "garlic"), (2, "can", "can", "garlic"), (4, "slices", "slice", "garlic"), (1, "boxes", "box", "garlic"),
    (2, "shell", "count", "garlic"), (1, "pkg", "package", "garlic"),
    (None, "clove", None, "garlic"), (None, "cup", None, "garlic"), (None, None, None, "garlic"), (0, "cup", None, "garlic"),
]


@pytest.mark.parametrize("amount,unit,want_unit,want_name", CASES)
def test_line_unit_normalizes_every_unit(amount, unit, want_unit, want_name):
    assert units.line_unit(amount, unit, "garlic") == (want_unit, want_name)


def test_line_unit_keeps_the_name_and_survives_long_words():
    assert units.line_unit(2, "clove", "garlic cloves") == ("clove", "garlic cloves")
    assert units.line_unit(2, "x" * 80, "thing") == ("count", "thing")
    assert units.known_unit("Tbsp.") == "tbsp" and units.known_unit("Cloves") == "clove" and units.known_unit("shell") is None
    assert units.known_unit("") is None


def test_taste_line_moves_the_phrase_into_the_note():
    assert units.taste_line("salt to taste", None, None, "salt to taste") == ("salt", "to taste")
    assert units.taste_line("x", "to taste", None, "salt") == ("salt", "to taste")
    assert units.taste_line("x", "fine, as needed", None, "pepper") == ("pepper", "fine, as needed")
    assert units.taste_line("pepper", None, "to taste", "pepper") == ("pepper", "to taste")
    assert units.taste_line("2 eggs", None, None, "egg") is None


ROWS = {"name": "Stew", "servings": 2, "confidence": "Clear.", "ingredients": [
    {"text": "3 carrots", "amount": 3, "unit": None, "name": "carrots", "note": None},
    {"text": "2 cloves garlic", "amount": 2, "unit": "clove", "name": "garlic", "note": "minced"},
    {"text": "1 can tomatoes", "amount": 1, "unit": "can", "name": "tomatoes", "note": None},
    {"text": "2 tablespoons oil", "amount": 2, "unit": "tablespoons", "name": "oil", "note": None},
    {"text": "a pinch of salt", "amount": None, "unit": "pinch", "name": "salt", "note": None},
    {"text": "Salt to taste", "amount": 1, "unit": "tsp", "name": "salt", "note": None},
    {"text": "Pepper", "amount": None, "unit": None, "name": "pepper", "note": "as needed"},
    {"text": "Fresh parsley", "amount": None, "unit": None, "name": "parsley", "note": None}]}
WANT = [(3, "count", "carrots", None), (2, "clove", "garlic", "minced"), (1, "can", "tomatoes", None), (2, "tbsp", "oil", None),
        (None, None, "salt", None), (1, "tsp", "salt", None), (None, None, "pepper", "as needed"), (None, None, "parsley", None)]


def shape(recipe):
    return [(i["amount"], i["unit"], i["name"], i["note"]) for i in recipe["ingredients"]]


def check(recipe):
    got = shape(recipe)
    # "a pinch of salt" has no amount: the unit is dropped and the line stays text
    assert got == WANT
    assert recipe["ingredients"][6]["text"] == "pepper, as needed"
    assert all(i["unit"] in (None, *units.KNOWN) for i in recipe["ingredients"])  # never a custom unit


def test_text_import_normalizes_units(env):
    env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, ROWS)
    r = env["c"].post("/api/recipes/import/text", json={"text": "stew"})
    assert r.status_code == 200, r.text
    check(r.json()["recipe"])


def test_photo_import_normalizes_units(env):
    env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, ROWS)
    r = env["c"].post("/api/recipes/import/photos", files=[("images", ("a.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 200, r.text
    check(r.json()["recipe"])


def test_url_import_normalizes_units(env, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_RECIPE_URL", "1")
    env["reply"] = url_tests.reply({**ROWS, "cut_off": False})
    r = env["c"].post("/api/recipes/import/url", json={"url": url_tests.URL})
    assert r.status_code == 200, r.text
    check(r.json()["recipe"])


def test_import_prompts_and_schema_list_the_units_and_the_to_taste_rule():
    for text in (recipe_ai.import_text_request("x", "")["messages"][0]["content"][0]["text"],
                 recipe_ai.import_photo_request([("image/jpeg", JPEG)], "")["messages"][0]["content"][-1]["text"],
                 recipe_ai.import_url_request("https://a.example/r", "")["messages"][0]["content"][0]["text"]):
        assert "Use only these units: " + ", ".join(recipe_ai.UNIT_NAMES) in text and "Use count when the line gives no unit" in text
        assert "to taste or as needed" in text and "leave amount and unit null" in text
    assert recipe_ai.UNIT_NAMES == ("g", "kg", "oz", "lb", "ml", "l", "floz", "cup", "tbsp", "tsp", "count", *units.PACKAGE_UNITS, *units.FUZZY_UNITS)
    for word in ("can", "clove", "stick", "pinch", "fillet", "carton"):
        assert word in recipe_ai.UNIT_NAMES
    assert "leave it out of the name" in recipe_ai.UNIT_RULE and "printed package size" in recipe_ai.UNIT_RULE
    props = recipe_ai.IMPORT_TOOL["input_schema"]["properties"]["ingredients"]["items"]["properties"]
    assert "count" in props["unit"]["description"] and "to taste" in props["note"]["description"] and "to taste" in props["amount"]["description"]
    assert recipe_ai.URL_IMPORT_TOOL["input_schema"]["properties"]["ingredients"] == recipe_ai.IMPORT_TOOL["input_schema"]["properties"]["ingredients"]
    assert "count" in recipe_ai.MATCH_TOOL["input_schema"]["properties"]["matches"]["items"]["properties"]["unit"]["description"]
    assert "UNIT" not in recipe_ai.MATCH_INSTRUCTION and ", ".join(recipe_ai.UNIT_NAMES) in recipe_ai.MATCH_INSTRUCTION


def test_clean_unit_keeps_only_known_units():
    assert [recipe_ai.clean_unit(x) for x in ("Cups", "clove", "", None, "Tbsp.", "pinch", "count")] == ["cup", "clove", None, None, "tbsp", "pinch", "count"]


def test_saving_an_import_makes_an_amount_with_no_unit_a_count(env):
    m = env["c"].post("/api/meals/import", json={"name": "S", "ingredients": [
        {"name": "carrots", "amount": 3}, {"name": "carrots", "amount": 3, "unit": ""}, {"name": "salt"}, {"name": "x", "amount": 1, "unit": "pinch"}]}).json()
    src = [(i["src"]["amount"], i["src"]["unit"], i["src"]["text"]) for i in m["items"]]
    assert src == [(3, "count", "3 carrots"), (3, "count", "3 carrots"), (None, None, "salt"), (1, "pinch", "1 pinch x")]  # a unit the user typed stays


def test_match_routes_never_return_a_custom_unit(env):
    m = saved_recipe(env, [{"text": "3 carrots", "amount": 3, "name": "flour"}, {"text": "2 cloves", "amount": 2, "unit": "clove", "name": "flour"},
                           {"text": "salt", "name": "flour"}])
    ids = [i["id"] for i in m["items"]]
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [
        {"row": 1, "choice": 1, "amount": 3, "unit": "bunch", "estimate": None, "note": None},
        {"row": 2, "choice": 1, "amount": 2, "unit": "Cloves", "estimate": None, "note": None},
        {"row": 3, "choice": 1, "amount": 2, "unit": "tbsp", "estimate": None, "note": None}]})
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": ids}).json()["proposals"]
    # a count or a clove of a cup label food has no known weight (issue #45): Check Amount, never label servings
    assert [(x["amount"], x["unit"], x["check"], x["check_reason"]) for x in p] == [(1, "cup", True, "no_weight"), (1, "cup", True, "no_weight"),
                                                                                     (2, "tbsp", False, None)]
    assert all(x["unit"] in units.KNOWN for x in p)


def test_claude_match_estimate_on_a_count_label_uses_the_label_word(env):
    m = saved_recipe(env, [{"text": "2 eggs", "amount": 2, "name": "egg"}, {"text": "1 shell", "amount": 1, "unit": "shell", "name": "egg"}])
    ids = [i["id"] for i in m["items"]]
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [{"row": 1, "choice": 1, "amount": 2, "unit": None, "estimate": None, "note": None},
                                                                  {"row": 2, "choice": 1, "amount": 1, "unit": "shell", "estimate": None, "note": None}]})
    env["off"]["egg"] = [EGG_OFF]
    p = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": ids}).json()["proposals"]
    assert [(x["kind"], x["amount"], x["unit"], x["check"]) for x in p] == [("candidate", 2, "egg", False), ("candidate", 1, "egg", False)]


def test_search_never_returns_a_custom_unit_and_treats_no_unit_as_count(env):
    env["fdc"]["flour"] = [FLOUR]
    env["off"]["egg"] = [EGG_OFF]
    m = saved_recipe(env, [{"amount": 3, "name": "flour"}, {"amount": 3, "unit": "", "name": "flour"}, {"amount": 2, "name": "egg"},
                           {"amount": 2, "unit": "shell", "name": "egg"}, {"amount": 4, "unit": "slice", "name": "flour"}])
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [i["id"] for i in m["items"]]}).json()["proposals"]
    assert [(x["amount"], x["unit"], x["check"]) for x in p] == [(1, "cup", True), (1, "cup", True), (2, "egg", False),
                                                                (2, "egg", False), (1, "cup", True)]
    assert [x["check_reason"] for x in p] == ["no_weight", "no_weight", None, None, "no_weight"]


def test_match_amount_custom_flag():
    food = {"serving_amount": 1, "serving_unit": "cup", "serving_g": 125}
    no_weight = {"amount": 1, "unit": "cup", "check": True, "reason": "no_weight"}
    assert units.match_amount(food, 2, "pinch") == no_weight and units.match_amount(food, 2, "pinch", custom=False) == no_weight
    assert units.match_amount(food, 2, "shell") == no_weight and units.match_amount(food, 2, None) == no_weight
    egg = {"serving_amount": 1, "serving_unit": "egg"}
    assert units.match_amount(egg, 2, "shell") == {"amount": 2, "unit": "shell", "check": False}  # the user's own word stays by default
    assert units.match_amount(egg, 2, "shell", custom=False) == {"amount": 2, "unit": "egg", "check": False}
    assert units.match_amount(food, None, "") is None
    slice_food = {"serving_amount": 2, "serving_unit": "slice"}
    assert units.match_amount(slice_food, 3, "Slices", custom=False) == {"amount": 3, "unit": "slice", "check": False}  # the label's own word
    assert units.match_amount(slice_food, 3, "", custom=False) == {"amount": 3, "unit": "slice", "check": False}
    assert units.match_amount(food, 1, "cup", custom=False) == {"amount": 1, "unit": "cup", "check": False}
    assert units.match_amount(food, 1, "tsp", custom=False)["unit"] == "tsp"
