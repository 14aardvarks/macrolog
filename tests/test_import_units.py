"""Issue #55: a recipe import uses only weights and volumes. Claude turns counts, package and fuzzy units into a weight or volume
(estimated, the original wording in the note); a printed size wins; stray units are converted through the typical weight tables or
kept for a check; a real portion replaces the estimate at match time."""
import pytest

from app import core, db, recipe_ai, units
from tests.test_food_units import food
from tests.test_recipe_ai import JPEG, env, reply  # noqa: F401
from tests import test_recipe_url as url_tests

CLAUDE = {"name": "Curry", "servings": 4, "confidence": "Clear.", "steps": [], "ingredients": [
    {"text": "3 cloves garlic, minced", "amount": 9, "unit": "g", "name": "garlic", "note": "3 cloves, minced", "estimated": True},
    {"text": "1 can coconut milk", "amount": 13.5, "unit": "fl oz", "name": "coconut milk", "note": "1 can", "estimated": True},
    {"text": "a pinch of salt", "amount": 0.36, "unit": "g", "name": "salt", "note": None, "estimated": True},
    {"text": "2 eggs", "amount": 100, "unit": "g", "name": "eggs", "note": "2 eggs", "estimated": True},
    {"text": "1 (15 oz) can chickpeas, drained", "amount": 425, "unit": "g", "name": "chickpeas", "note": "drained", "estimated": True},
    {"text": "1 cup rice", "amount": 1, "unit": "cup", "name": "rice", "note": None, "estimated": False},
    # stray units Claude should not send: a clove the table knows, a count it does not
    {"text": "2 cloves garlic", "amount": 2, "unit": "clove", "name": "garlic", "note": None, "estimated": False},
    {"text": "3 widgets", "amount": 3, "unit": "count", "name": "widgets", "note": None, "estimated": False},
    {"text": "Salt to taste", "amount": None, "unit": None, "name": "salt", "note": "to taste", "estimated": False}]}
WANT = [
    (9, "g", "3 cloves, minced", True, "ai", 3, "clove"),
    (13.5, "floz", "1 can", True, "ai", 1, "can"),
    (0.36, "g", "1 pinch", True, "ai", 1, "pinch"),
    (100, "g", "2 eggs", True, "ai", 2, "count"),
    (15, "oz", "1 can, drained", False, None, None, None),  # the printed size wins over Claude's 425 g
    (1, "cup", None, False, None, None, None),
    (6, "g", "2 cloves", True, "table", 2, "clove"),
    (3, "count", None, False, None, None, None),  # nothing knows a widget: kept for a check
    (None, None, "to taste", False, None, None, None)]


def shape(recipe):
    return [(i["amount"], i["unit"], i["note"], i["estimated"], i["est_source"], i["was_amount"], i["was_unit"]) for i in recipe["ingredients"]]


def unions(node):
    if isinstance(node, dict):
        return (isinstance(node.get("type"), list) or "anyOf" in node) + sum(unions(v) for v in node.values())
    return sum(unions(v) for v in node) if isinstance(node, list) else 0


def test_schema_adds_a_plain_boolean_and_keeps_the_union_limit():
    item = recipe_ai.IMPORT_TOOL["input_schema"]["properties"]["ingredients"]["items"]
    assert item["properties"]["estimated"] == {"type": "boolean", "description": item["properties"]["estimated"]["description"]}
    assert "estimated" in item["required"]
    assert unions(recipe_ai.IMPORT_TOOL["input_schema"]) == 5 and unions(recipe_ai.URL_IMPORT_TOOL["input_schema"]) <= 16


def test_every_import_prompt_carries_the_measures_and_the_typical_weights():
    for text in (recipe_ai.import_text_request("x", "")["messages"][0]["content"][0]["text"],
                 recipe_ai.import_photo_request([("image/jpeg", JPEG)], "")["messages"][0]["content"][-1]["text"],
                 recipe_ai.import_url_request("https://a.example/r", "")["messages"][0]["content"][0]["text"]):
        assert "Use only these units: g, kg, oz, lb, ml, l, floz, cup, tbsp, tsp." in text
        assert "Never use count" in text and "estimated true" in text and "original wording in note" in text
        for bit in ("garlic clove 3", "egg 50", "onion 110", "carrot 61", "pinch of a spice or salt 0.36", "beans or chickpeas 15 oz",
                    "coconut milk 13.5 fl oz", "tomato paste 6 oz", "diced or crushed tomatoes 14.5 oz", "A size printed on the line wins"):
            assert bit in text
        assert "Do not convert units" not in text


@pytest.mark.parametrize("route", ["text", "photos", "url"])
def test_all_three_imports_convert_and_mark_estimates(env, monkeypatch, route):
    if route == "url":
        monkeypatch.setenv("AI_ALLOW_RECIPE_URL", "1")
        env["reply"] = url_tests.reply({**CLAUDE, "cut_off": False})
        r = env["c"].post("/api/recipes/import/url", json={"url": url_tests.URL})
    elif route == "photos":
        env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, CLAUDE)
        r = env["c"].post("/api/recipes/import/photos", files=[("images", ("a.jpg", JPEG, "image/jpeg"))])
    else:
        env["reply"] = reply(recipe_ai.IMPORT_TOOL_NAME, CLAUDE)
        r = env["c"].post("/api/recipes/import/text", json={"text": "curry"})
    assert r.status_code == 200, r.text
    got = shape(r.json()["recipe"])
    assert got == WANT
    assert all(i["unit"] in (None, *units.MEASURES, "count") for i in r.json()["recipe"]["ingredients"])


def test_claude_forgetting_the_flag_is_still_estimated_from_the_line():
    draft, _ = recipe_ai.clean_recipe({"ingredients": [{"text": "1 onion", "amount": 110, "unit": "g", "name": "onion", "note": None}]})
    assert shape(draft) == [(110, "g", "1 onion", True, "ai", 1, "count")]


def save(env, rows):
    r = env["c"].post("/api/meals/import", json={"name": "Curry", "ingredients": rows})
    assert r.status_code == 200, r.text
    return r.json()


GARLIC_ROW = {"text": "3 cloves garlic", "amount": 9, "unit": "g", "name": "garlic", "note": "3 cloves", "estimated": True,
              "est_source": "ai", "was_amount": 3, "was_unit": "clove"}


def test_import_stores_the_estimate_and_the_original_wording(env):
    m = save(env, [GARLIC_ROW, {**GARLIC_ROW, "text": "1 can coconut milk", "amount": 13.5, "unit": "fl oz", "name": "coconut milk",
                                 "was_amount": 1, "was_unit": "can", "est_source": "table"},
                   {"text": "1 cup rice", "amount": 1, "unit": "cup", "name": "rice", "estimated": False},
                   {"text": "3 cloves", "amount": 3, "unit": "clove", "name": "garlic", "estimated": True}])  # an old unit is never estimated
    s = [(i["src"]["unit"], i["src"]["estimated"], i["src"]["est_source"], i["src"]["was_amount"], i["src"]["was_unit"]) for i in m["items"]]
    assert s == [("g", True, "ai", 3, "clove"), ("floz", True, "table", 1, "can"), ("cup", False, None, None, None),
                 ("clove", False, None, None, None)]
    dup = env["c"].post(f"/api/meals/{m['id']}/duplicate").json()
    assert [i["src"]["est_source"] for i in dup["items"]] == ["ai", "table", None, None]


@pytest.mark.parametrize("bad", [{"estimated": "yes"}, {"est_source": "magic"}])
def test_import_validates_the_estimate(env, bad):
    r = env["c"].post("/api/meals/import", json={"name": "C", "ingredients": [{**GARLIC_ROW, **bad}]})
    assert r.status_code == 400


def test_old_units_still_import_and_show_a_weight_reason_when_nothing_knows_them(env):
    m = save(env, [{"text": "3 widgets", "amount": 3, "unit": "count", "name": "widgets"},
                   {"text": "2 eggs", "amount": 2, "unit": "count", "name": "eggs"},
                   {"text": "1 can mystery", "amount": 1, "unit": "can", "name": "mystery"},
                   {"text": "2 slices bread", "amount": 2, "unit": "slice", "name": "bread"}])
    assert [(i["src"]["unit"], i["src"]["weight_reason"]) for i in m["items"]] == [
        ("count", "no_weight"), ("count", None), ("can", "no_size"), ("slice", None)]


def test_matching_keeps_the_estimate_with_its_tag(env):
    garlic = env["c"].post("/api/foods", json=food("Garlic, raw")).json()  # a 100 g label, only the table knows a clove
    m = save(env, [GARLIC_ROW])
    iid = m["items"][0]["id"]
    env["fdc"]["garlic"] = []
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [iid]}).json()["proposals"][0]
    assert p["food"] is not None
    p = env["c"].patch(f"/api/meals/{m['id']}/items/{iid}", json={"food_id": garlic["id"], "amount": 9, "unit": "g"}).json()["items"][0]
    assert (p["amount"], p["unit"], p["estimated"], p["estimate_source"], p["weight_source"], p["weight_note"], p["weight_grams"],
            p["line_estimate"]) == (9, "g", True, "claude", "ai", units.AI_NOTE, 9, True)
    with db.conn() as c:  # an import estimate is never saved as the user's weight
        assert c.execute("SELECT COUNT(*) FROM food_units").fetchone()[0] == 0


def test_search_proposal_carries_the_estimate(env):
    env["fdc"]["garlic"] = [{**food("Garlic, raw"), "source": "fdc", "source_id": "g1", "label_text": "100 g"}]
    m = save(env, [GARLIC_ROW])
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"][0]
    assert (p["amount"], p["unit"], p["estimated"], p["estimate_source"], p["weight_source"], p["line_estimate"]) == (9, "g", True, "claude", "ai", True)


@pytest.mark.parametrize("source,uid", [("fdc", None), ("off", None), ("user", 1)])
def test_a_real_portion_replaces_the_estimate(env, source, uid):
    garlic = env["c"].post("/api/foods", json=food("Garlic, raw")).json()
    with db.conn() as c:
        core.save_unit_weight(c, garlic["id"], uid, "clove", 4, source)
    env["fdc"]["garlic"] = []
    env["off"]["garlic"] = []
    m = save(env, [GARLIC_ROW])
    iid = m["items"][0]["id"]
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [iid]}).json()["proposals"][0]
    assert p["food"]["id"] == garlic["id"]
    assert (p["amount"], p["unit"], p["estimated"], p["weight_source"], p.get("line_estimate")) == (3, "clove", False, source, None)
    assert p["weight_grams"] == 12
    row = env["c"].patch(f"/api/meals/{m['id']}/items/{iid}", json={"food_id": garlic["id"], "amount": 3, "unit": "clove"}).json()["items"][0]
    assert (row["estimated"], row["weight_source"], row.get("line_estimate")) == (False, source, None)


def test_a_table_or_claude_weight_does_not_replace_the_estimate(env):
    garlic = env["c"].post("/api/foods", json=food("Garlic, raw")).json()
    with db.conn() as c:
        core.save_unit_weight(c, garlic["id"], 1, "clove", 5, "ai", True)
        assert units.trusted_was(core.need_food(c, garlic["id"], 1), 3, "clove") is None
    m = save(env, [GARLIC_ROW])
    env["fdc"]["garlic"] = []
    env["off"]["garlic"] = []
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"][0]
    assert (p["amount"], p["unit"], p["line_estimate"]) == (9, "g", True)


def test_a_count_word_label_replaces_an_egg_estimate(env):
    egg = env["c"].post("/api/foods", json=food("Egg", 1, "egg", serving_g=48)).json()
    m = save(env, [{"text": "2 eggs", "amount": 100, "unit": "g", "name": "eggs", "note": "2 eggs", "estimated": True,
                    "was_amount": 2, "was_unit": "count"}])
    env["off"]["eggs"] = []
    env["fdc"]["eggs"] = []
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"][0]
    assert p["food"]["id"] == egg["id"] and (p["amount"], p["unit"], p["estimated"]) == (2, "egg", False)


def test_typed_grams_replace_the_estimate_and_become_the_users_weight(env):
    garlic = env["c"].post("/api/foods", json=food("Garlic, raw")).json()
    m = save(env, [GARLIC_ROW])
    iid = m["items"][0]["id"]
    base = f"/api/meals/{m['id']}/items/{iid}"
    env["c"].patch(base, json={"food_id": garlic["id"], "amount": 9, "unit": "g"})
    row = env["c"].patch(base, json={"food_id": garlic["id"], "amount": 15, "unit": "g", "remember": True}).json()["items"][0]
    assert row["estimated"] is False and row.get("line_estimate") is None and row["src"]["estimated"] is False
    units_ = env["c"].get(f"/api/foods/{garlic['id']}/units").json()["units"]
    assert [(u["unit"], u["grams"], u["source"]) for u in units_ if u["source"] == "user"] == [("clove", 5, "user")]


def test_claude_match_keeps_the_estimate_too(env):
    garlic = env["c"].post("/api/foods", json=food("Garlic, raw")).json()
    env["fdc"]["garlic"] = []
    env["off"]["garlic"] = []
    m = save(env, [GARLIC_ROW])
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": [
        {"row": 1, "choice": 1, "amount": 9, "unit": "g", "estimate": None, "note": None, "unit_grams": None, "density_g_per_cup": None}]})
    r = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [m["items"][0]["id"]]})
    assert r.status_code == 200, r.text
    p = r.json()["proposals"][0]
    assert p["food"]["id"] == garlic["id"]
    assert (p["amount"], p["unit"], p["estimated"], p["estimate_source"], p["weight_source"]) == (9, "g", True, "claude", "ai")
