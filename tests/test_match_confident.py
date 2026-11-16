"""Match With Claude (issue #56) accepts a proposal on its own only when it is confident: Search for an earlier recipe's food or
the same name, Claude for a chosen candidate at medium or high match_confidence (units.AI_CONFIDENT). Everything else waits."""
import pytest

from app import recipe_ai, units
from tests.test_recipe_ai import env, reply  # noqa: F401
from tests.test_previous_match import food, recipe, search, claude_match


def row(n, choice, conf="high", **kw):
    return {"row": n, "choice": choice, "amount": 1, "unit": "cup", "estimate": None, "note": None, "match_confidence": conf,
            "unit_grams": None, "density_g_per_cup": None, **kw}


def test_match_tool_asks_for_match_confidence():
    item = recipe_ai.MATCH_TOOL["input_schema"]["properties"]["matches"]["items"]
    assert "match_confidence" in item["required"]
    assert item["properties"]["match_confidence"]["enum"] == ["low", "medium", "high"]
    assert "match_confidence" in recipe_ai.MATCH_INSTRUCTION
    assert units.AI_CONFIDENT == ("medium", "high")


def test_search_same_name_and_previous_are_confident_closest_name_is_not(env):
    food(env, "Butter")
    food(env, "Tahini Paste Smooth")
    mine = food(env, "My Special Flour")
    recipe(env, ["flour"], matches={"flour": mine})
    m = recipe(env, ["butter", "tahini paste", "flour", "zzqx"])
    p = {x["item_id"]: x for x in search(env, m)}
    ids = [i["id"] for i in m["items"]]
    assert p[ids[0]]["confident"] is True and p[ids[0]]["note"].startswith("Same name")
    assert p[ids[1]]["food"] and p[ids[1]]["confident"] is False and p[ids[1]]["note"].startswith("Closest name")
    assert p[ids[2]]["from_previous"] is True and p[ids[2]]["confident"] is True
    assert p[ids[3]]["food"] is None and p[ids[3]]["confident"] is False


@pytest.mark.parametrize("conf,expect", [("high", True), ("medium", True), ("low", False), (None, False), ("sure", False)])
def test_claude_choice_is_confident_at_medium_or_high(env, conf, expect):
    food(env, "Butter")
    m = recipe(env, ["butter"])
    data = row(1, 1, conf)
    if conf is None:
        del data["match_confidence"]  # an older or odd answer without it is never accepted on its own
    p = claude_match(env, m, reply_data=[data])[0]
    assert p["kind"] == "candidate" and p["confident"] is expect


def test_claude_estimate_none_and_previous_fallback_are_not_confident(env):
    est = {"name": "Mystery Spice", "serving_amount": 1, "serving_unit": "tsp", "serving_g": 2, "kcal": 5, "carbs": 1, "protein": 0, "fat": 0}
    m = recipe(env, ["mystery spice", "water"])
    p = claude_match(env, m, reply_data=[row(1, None, "high", estimate=est), row(2, None, "high")])
    assert p[0]["kind"] == "estimate" and p[0]["confident"] is False
    assert p[1]["kind"] == "none" and p[1]["confident"] is False
    mine = food(env, "Saffron Gold")
    recipe(env, ["saffron"], matches={"saffron": mine})
    p = claude_match(env, recipe(env, ["saffron"]), reply_data=[row(1, None, "high")])[0]
    assert p["from_previous"] is True and p["confident"] is False  # Claude passed on it, so it waits for a look
