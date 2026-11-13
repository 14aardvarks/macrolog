"""From Previous Recipe: an ingredient name matched to a food in an earlier visible recipe is proposed first, by Search and
by Claude (as a hint). Normalization, ordering, privacy and deleted foods."""
import pytest

from app import db, ingredients, recipe_ai
from tests.test_recipe_ai import env, reply, usage_count  # noqa: F401

FOOD = {"serving_amount": 1, "serving_unit": "cup", "serving_g": 100, "kcal": 100, "carbs": 10, "protein": 5, "fat": 2}


def food(env, name, client="c"):
    return env[client].post("/api/foods", json={**FOOD, "name": name}).json()


def recipe(env, names, client="c", matches=None, shared=False):
    """A recipe with one imported row per name. matches: {name: food} matched at once. Returns the meal."""
    rows = [{"text": f"1 cup {n}", "amount": 1, "unit": "cup", "name": n} for n in names]
    m = env[client].post("/api/meals/import", json={"name": "R", "ingredients": rows}).json()
    for it, n in zip(m["items"], names):
        if matches and n in matches:
            r = env[client].patch(f"/api/meals/{m['id']}/items/{it['id']}", json={"food_id": matches[n]["id"], "amount": 1, "unit": "cup"})
            assert r.status_code == 200, r.text
    if shared:
        env[client].patch(f"/api/meals/{m['id']}", json={"shared": True})
    return env[client].get(f"/api/meals/{m['id']}").json()


def search(env, m, client="c", **body):
    r = env[client].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [i["id"] for i in m["items"]], **body})
    assert r.status_code == 200, r.text
    return r.json()["proposals"]


# ---------- normalization ----------

@pytest.mark.parametrize("text,expect", [
    ("tomato", "tomato"), ("Tomatoes", "tomato"), ("2 cups Chopped fresh Tomatoes, divided", "tomato"),
    ("large eggs", "egg"), ("Egg", "egg"), ("cloves garlic, minced", "garlic"), ("250g butter", "butter"),
    ("1 1/2 cups all-purpose flour", "all flour purpose"), ("beef ground", "beef ground"), ("1/2 lb ground beef", "beef ground"),
    ("Olive oil (extra virgin)", "oil olive"), ("berries", "berry"), ("Hummus", "hummus"),
    ("½ tsp salt", "salt"), ("  ", None), ("", None), (None, None), ("2 cups", None), ("chopped", None),
])
def test_key_normalizes_quantities_units_prep_and_plurals(text, expect):
    assert ingredients.key(text) == expect


def test_key_keeps_words_that_change_the_food():
    assert ingredients.key("whole milk") != ingredients.key("milk")
    assert ingredients.key("brown sugar") != ingredients.key("sugar")
    assert ingredients.key("dried basil") != ingredients.key("fresh basil")


def test_search_scoring_still_uses_the_light_normalizer():
    assert recipe_ai.name_score("tomatoes", "Tomato, raw")[0] == 2
    assert ingredients.words("The Eggs and berries") == frozenset({"egg", "berry"})


# ---------- Search proposals ----------

def test_search_proposes_the_food_an_earlier_recipe_matched_first(env):
    mine = food(env, "My Special Tomatoes")
    recipe(env, ["tomato"], matches={"tomato": mine})
    env["fdc"]["tomato"] = [{"source": "fdc", "source_id": "t1", "name": "Tomato, raw", "serving_amount": 1, "serving_unit": "cup",
                             "serving_g": 150, "label_text": "1 cup (150 g)", "kcal": 30, "carbs": 6, "protein": 1.5, "fat": 0.3}]
    later = recipe(env, ["Chopped fresh tomatoes, diced"])
    p = search(env, later)[0]
    assert p["food"]["id"] == mine["id"] and p["from_previous"] is True and p["method"] == "search" and p["kind"] == "candidate"
    assert p["note"] == "Matched to this food in an earlier recipe" and (p["amount"], p["unit"]) == (1, "cup")
    assert env["searches"] == [] and usage_count() == 0  # no lookup for a row an earlier recipe answered, and no Claude


def test_rows_without_an_earlier_match_search_as_before(env):
    recipe(env, ["tomato"], matches={"tomato": food(env, "Tomato Thing")})
    env["fdc"]["flour"] = [{"source": "fdc", "source_id": "f1", "name": "Wheat flour", "serving_amount": 1, "serving_unit": "cup",
                            "serving_g": 125, "label_text": "1 cup (125 g)", "kcal": 455, "carbs": 95, "protein": 13, "fat": 1.2}]
    p = search(env, recipe(env, ["tomato", "flour"]))
    assert p[0]["from_previous"] is True and "from_previous" not in p[1]
    assert p[1]["food"]["name"] == "Wheat flour" and p[1]["note"].endswith("USDA")


def test_most_recent_recipe_wins_even_over_a_more_frequent_food(env):
    old, new, often = food(env, "Old Milk"), food(env, "New Milk"), food(env, "Often Milk")
    recipe(env, ["milk"], matches={"milk": old})
    recipe(env, ["milk", "milk"], matches={"milk": often})
    recipe(env, ["milk"], matches={"milk": new})
    assert search(env, recipe(env, ["milk"]))[0]["food"]["id"] == new["id"]


def test_ties_inside_one_recipe_go_to_the_food_matched_more_often(env):
    a, b = food(env, "Milk A"), food(env, "Milk B")
    m = recipe(env, ["milk", "milk", "milk"])
    ids = [i["id"] for i in m["items"]]
    for i, f in zip(ids, (a, b, b)):
        env["c"].patch(f"/api/meals/{m['id']}/items/{i}", json={"food_id": f["id"], "amount": 1, "unit": "cup"})
    assert recipe_ai.previous_matches(1, ["Milk"])["milk"]["id"] == b["id"]
    env["c"].patch(f"/api/meals/{m['id']}/items/{ids[2]}", json={"food_id": a["id"], "amount": 1, "unit": "cup"})
    assert recipe_ai.previous_matches(1, ["milk"])["milk"]["id"] == a["id"]  # two against one, now A


def test_the_recipe_being_matched_and_unmatched_or_skipped_rows_never_count(env):
    f = food(env, "Egg Food")
    m = recipe(env, ["egg", "egg"], matches={"egg": f})  # both rows are in this very recipe
    assert recipe_ai.previous_matches(1, ["egg"], exclude_meal=m["id"]) == {}
    other = recipe(env, ["egg"])
    env["c"].patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"skipped": True})
    env["c"].patch(f"/api/meals/{m['id']}/items/{m['items'][1]['id']}", json={"food_id": None})
    assert recipe_ai.previous_matches(1, ["egg"]) == {} and "from_previous" not in search(env, other)[0]


def test_source_option_keeps_only_that_source(env):
    custom = food(env, "Custom Rice")
    recipe(env, ["rice"], matches={"rice": custom})
    assert recipe_ai.previous_matches(1, ["rice"], source="fdc") == {}
    assert recipe_ai.previous_matches(1, ["rice"], source="all")["rice"]["id"] == custom["id"]


# ---------- privacy ----------

def test_other_users_private_recipes_are_never_used(env):
    theirs = food(env, "Their Oats", "b")
    recipe(env, ["oat"], client="b", matches={"oat": theirs})
    mine = recipe(env, ["oat"])
    assert recipe_ai.previous_matches(1, ["oat"]) == {}
    assert "from_previous" not in search(env, mine)[0]
    assert env["b"].get(f"/api/meals/{mine['id']}").status_code == 404  # and it works the other way


def test_a_shared_recipe_counts_for_everyone_until_it_is_made_private(env):
    theirs = food(env, "Shared Oats", "b")
    shared = recipe(env, ["oat"], client="b", matches={"oat": theirs}, shared=True)
    assert recipe_ai.previous_matches(1, ["oat"])["oat"]["id"] == theirs["id"]
    assert search(env, recipe(env, ["oat"]))[0]["from_previous"] is True
    env["b"].patch(f"/api/meals/{shared['id']}", json={"shared": False})
    assert recipe_ai.previous_matches(1, ["oat"]) == {}


def test_my_own_recipes_beat_nothing_but_never_leak_to_the_other_user(env):
    mine = food(env, "My Oats")
    recipe(env, ["oat"], matches={"oat": mine})
    assert recipe_ai.previous_matches(2, ["oat"]) == {}


# ---------- deleted foods ----------

def test_deleted_foods_are_skipped_for_everyone_or_for_one_user(env):
    gone, kept = food(env, "Gone Honey"), food(env, "Kept Honey")
    recipe(env, ["honey"], matches={"honey": kept})
    recipe(env, ["honey"], matches={"honey": gone})  # newer, so it would win
    assert recipe_ai.previous_matches(1, ["honey"])["honey"]["id"] == gone["id"]
    with db.conn() as c:
        c.execute("UPDATE foods SET deleted=1 WHERE id=?", (gone["id"],))
    assert recipe_ai.previous_matches(1, ["honey"])["honey"]["id"] == kept["id"]
    with db.conn() as c:
        c.execute("UPDATE foods SET deleted=0 WHERE id=?", (gone["id"],))
        c.execute("INSERT INTO deleted_foods(user_id, food_id) VALUES (1, ?)", (gone["id"],))
    assert recipe_ai.previous_matches(1, ["honey"])["honey"]["id"] == kept["id"]
    with db.conn() as c:
        c.execute("INSERT INTO deleted_foods(user_id, food_id) VALUES (1, ?)", (kept["id"],))
    assert recipe_ai.previous_matches(1, ["honey"]) == {}
    assert "from_previous" not in search(env, recipe(env, ["honey"]))[0]


# ---------- speed ----------

def test_one_query_per_call_and_none_when_there_is_nothing_to_find(env, monkeypatch):
    f = food(env, "Salt Food")
    recipe(env, ["salt", "pepper"], matches={"salt": f})
    seen = []
    orig = db.conn

    from contextlib import contextmanager

    @contextmanager
    def traced():
        with orig() as c:
            c.set_trace_callback(seen.append)
            yield c

    monkeypatch.setattr(db, "conn", traced)
    assert recipe_ai.previous_matches(1, ["salt", "pepper", "water", "Salt"])["salt"]["id"] == f["id"]
    assert len([q for q in seen if q.lstrip().upper().startswith("SELECT")]) == 1  # one query for every name
    seen.clear()
    assert recipe_ai.previous_matches(1, ["", "2 cups", None]) == {}
    assert seen == []


# ---------- the Claude route ----------

def claude_match(env, m, rows=None, reply_data=None):
    ids = rows or [i["id"] for i in m["items"]]
    if reply_data is not None:
        env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": reply_data})
    r = env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": ids})
    assert r.status_code == 200, r.text
    return r.json()["proposals"]


def sent(env):
    return env["requests"][-1]["messages"][0]["content"][0]["text"]


def test_claude_gets_the_earlier_match_as_candidate_one_with_a_hint(env):
    mine = food(env, "My Special Flour")
    recipe(env, ["flour"], matches={"flour": mine})
    m = recipe(env, ["flour", "salt"])
    p = claude_match(env, m, reply_data=[
        {"row": 1, "choice": 1, "amount": 1, "unit": "cup", "estimate": None, "note": "Same as before."},
        {"row": 2, "choice": None, "amount": None, "unit": None, "estimate": None, "note": "No calories."}])
    text = sent(env)
    assert "earlier match: [1]" in text.split('<ingredient row="1">')[1].split("</ingredient>")[0]
    assert "earlier match" not in text.split('<ingredient row="2">')[1]
    assert "[1] My Special Flour" in text and "Prefer that candidate" in text
    assert p[0]["food"]["id"] == mine["id"] and p[0]["from_previous"] is True and "from_previous" not in p[1]


def test_claude_hints_are_one_per_row_and_never_name_other_users_private_recipes(env):
    theirs = food(env, "Zzyzx Private Stuff", "b")
    recipe(env, ["flour"], client="b", matches={"flour": theirs})
    m = recipe(env, ["flour"])
    claude_match(env, m, reply_data=[{"row": 1, "choice": None, "amount": None, "unit": None, "estimate": None, "note": None}])
    assert "Zzyzx" not in sent(env) and "earlier match" not in sent(env) and "Prefer that candidate" not in sent(env)


def test_an_earlier_match_is_used_when_claude_chooses_nothing(env):
    mine = food(env, "Saffron Gold")
    recipe(env, ["saffron"], matches={"saffron": mine})
    p = claude_match(env, recipe(env, ["saffron"]), reply_data=[{"row": 1, "choice": None, "amount": None, "unit": None, "estimate": None, "note": "Unsure."}])[0]
    assert p["kind"] == "candidate" and p["food"]["id"] == mine["id"] and p["from_previous"] is True
    # a Claude answer that is missing altogether still gets the earlier match
    p = claude_match(env, recipe(env, ["saffron"]), reply_data=[])[0]
    assert p["food"]["id"] == mine["id"] and p["from_previous"] is True


def test_claude_may_pick_another_candidate_and_then_it_is_not_from_previous(env):
    mine = food(env, "Wheat Flour Old")
    recipe(env, ["flour"], matches={"flour": mine})
    env["fdc"]["flour"] = [{"source": "fdc", "source_id": "f9", "name": "Flour, wheat", "serving_amount": 1, "serving_unit": "cup",
                            "serving_g": 125, "label_text": "1 cup (125 g)", "kcal": 455, "carbs": 95, "protein": 13, "fat": 1.2}]
    p = claude_match(env, recipe(env, ["flour"]), reply_data=[{"row": 1, "choice": 2, "amount": 1, "unit": "cup", "estimate": None, "note": None}])[0]
    assert p["food"]["name"] == "Flour, wheat" and "from_previous" not in p


def test_a_deleted_earlier_food_is_not_a_hint(env):
    gone = food(env, "Gone Stuff")
    recipe(env, ["flour"], matches={"flour": gone})
    with db.conn() as c:
        c.execute("UPDATE foods SET deleted=1 WHERE id=?", (gone["id"],))
    claude_match(env, recipe(env, ["flour"]), reply_data=[{"row": 1, "choice": None, "amount": None, "unit": None, "estimate": None, "note": None}])
    assert "Gone Stuff" not in sent(env) and "earlier match" not in sent(env)
