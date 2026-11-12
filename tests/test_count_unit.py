"""Count and the blank unit (issue #34): every food offers them, recipe lines need neither amount nor unit."""
import pytest

from app import units
from tests.test_core import BREAD, PB, a, b, env, food  # noqa: F401
from tests.test_recipe_match import imported
from tests.test_units import EGG, FLOUR_CUP, FLOUR_G, food as unit_food

SALT_LINE = {"name": "salt", "note": "to taste"}


def test_every_food_offers_count_and_none_last():
    for f in (FLOUR_G, FLOUR_CUP, EGG, unit_food(2, "serving")):
        us = [u["unit"] for u in units.available_units(f)]
        assert us[-2:] == ["count", ""] or us[-1] == ""  # a label of count word keeps its own word first
        assert "count" in us and "" in us
    labels = {u["unit"]: u["label"] for u in units.available_units(FLOUR_G)}
    assert labels["count"] == "Count" and labels[""] == "None"


def test_count_and_blank_scale_like_a_plain_count():
    assert units.servings_for(FLOUR_G, 2, "count")["servings"] == 2  # not a count word label: one serving each
    assert units.servings_for(FLOUR_G, 2, "")["servings"] == 2
    assert units.servings_for(FLOUR_G, 2, None)["servings"] == 2
    assert units.servings_for(unit_food(2, "slice"), 3, "count")["servings"] == 1.5  # the label's count word
    assert units.servings_for(unit_food(2, "slice"), 3, "")["servings"] == 1.5
    assert units.scale(EGG, 3, "count")["kcal"] == pytest.approx(216)
    assert units.servings_for(EGG, 1, "count")["estimated"] is False


@pytest.mark.parametrize("text", ["", None, "-", "none", "None"])
def test_unit_or_blank(text):
    assert units.unit_or_blank(text) == ""
    assert units.parse_unit("Count") == "count"


def test_match_amount_skips_blank_amount_and_handles_blank_unit_and_count():
    for amount in (None, "", 0):
        assert units.match_amount(EGG, amount, "count") is None
        assert units.match_amount(FLOUR_G, amount, "") is None
    assert units.match_amount(EGG, 2, "count") == {"amount": 2, "unit": "egg", "check": False}
    assert units.match_amount(EGG, 2, "") == {"amount": 2, "unit": "egg", "check": False}
    assert units.match_amount(FLOUR_G, 2, "Count") == {"amount": 2, "unit": "serving", "check": False}
    assert units.match_amount(FLOUR_G, 2, None) == {"amount": 2, "unit": "serving", "check": False}
    assert units.match_amount(unit_food(2, "slice"), 4, "count") == {"amount": 4, "unit": "slice", "check": False}


def test_log_entries_in_count_and_blank_unit(a):
    f = food(a, BREAD)
    for unit, shown in (("count", "count"), ("", "")):
        r = a.post("/api/entries", json={"food_id": f["id"], "amount": 2, "unit": unit})
        assert r.status_code == 200, r.text
        assert (r.json()["unit"], r.json()["kcal"]) == (shown, 180)
    p = a.get("/api/preview", params={"food_id": f["id"], "amount": 3, "unit": ""})
    assert p.status_code == 200 and p.json()["kcal"] == 270
    assert a.post("/api/entries", json={"food_id": f["id"], "amount": 2}).status_code == 200  # no unit sent at all
    assert a.post("/api/entries", json={"food_id": f["id"], "amount": 0, "unit": ""}).status_code == 400
    assert a.post("/api/entries", json={"food_id": f["id"], "amount": 1, "unit": "furlong"}).status_code == 400


def test_import_keeps_blank_amount_and_unit_as_plain_text(a):
    m = imported(a, [{"name": "bread", "amount": 2, "unit": "slice"}, SALT_LINE, {"text": "a pinch of salt", "name": "salt"},
                     {"name": "oil", "amount": 1}])
    src = [i["src"] for i in m["items"]]
    assert src[1] == {"text": "salt, to taste", "amount": None, "unit": None, "name": "salt", "note": "to taste"}
    assert src[2]["text"] == "a pinch of salt" and src[2]["amount"] is None
    assert src[3]["amount"] == 1 and src[3]["unit"] is None  # an amount alone saves too
    assert m["needed"] == 4


def test_match_with_count_and_blank_unit_then_log(a):
    m = imported(a, [{"name": "bread", "amount": 2}, {"name": "peanut butter", "amount": 2, "unit": "count"}, SALT_LINE])
    bread, pb = food(a, BREAD), food(a, PB)
    ids = [i["id"] for i in m["items"]]
    url = f"/api/meals/{m['id']}"
    r = a.patch(f"{url}/items/{ids[0]}", json={"food_id": bread["id"], "amount": 2, "unit": ""})
    assert r.status_code == 200, r.text
    r = a.patch(f"{url}/items/{ids[1]}", json={"food_id": pb["id"], "amount": 1, "unit": "count"}).json()
    assert [i["unit"] for i in r["items"][:2]] == ["", "count"] and r["matched"] == 2
    assert r["items"][2]["matched"] is False and r["items"][2]["src"]["text"] == "salt, to taste"
    log = a.post(url + "/log", json={})
    assert log.status_code == 200, log.text
    assert len(log.json()["entries"]) == 2  # the salt line is a reference line, never logged
    assert a.get(f"/api/meals/{m['id']}").json()["items"][2]["src"]["amount"] is None


def test_recipe_create_accepts_count_rows(a):
    f = food(a, BREAD)
    r = a.post("/api/meals", json={"name": "Toast", "items": [{"food_id": f["id"], "amount": 2, "unit": "count"},
                                                             {"food_id": f["id"], "amount": 1, "unit": ""}]})
    assert r.status_code == 200, r.text
    assert [i["unit"] for i in r.json()["items"]] == ["count", ""] and r.json()["kcal"] == 270


def test_claude_import_keeps_missing_units_blank():
    from app import recipe_ai
    for v in (None, "", "  ", "-", "none", "None"):
        assert recipe_ai.clean_unit(v) is None
    assert recipe_ai.clean_unit("Count") == "count" and recipe_ai.clean_unit("Tbsp.") == "tbsp"
    draft, _ = recipe_ai.clean_recipe({"name": "R", "ingredients": [{"text": "salt to taste", "amount": None, "unit": None, "name": "salt", "note": "to taste"}]})
    assert draft["ingredients"][0]["amount"] is None and draft["ingredients"][0]["unit"] is None
