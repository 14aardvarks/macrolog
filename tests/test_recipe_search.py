"""Match With Search: the best name match for ticked ingredients without Claude (no key, no credit, no request)."""
import pytest

from app import db, recipe_ai
from tests.test_recipe_ai import EGG_OFF, FLOUR, env, saved_recipe, usage_count  # noqa: F401

BUTTER_FDC = {"source": "fdc", "source_id": "b1", "name": "Butter, salted", "serving_amount": 1, "serving_unit": "tbsp", "serving_g": 14,
              "label_text": "1 tbsp (14 g)", "kcal": 100, "carbs": 0, "protein": 0.1, "fat": 11.5}
BUTTER_OFF = {"source": "off", "source_id": "b2", "name": "Butter", "serving_amount": 10, "serving_unit": "g", "serving_g": 10,
              "label_text": "10 g", "kcal": 74, "carbs": 0, "protein": 0.1, "fat": 8.2}
PB_FDC = {"source": "fdc", "source_id": "p1", "name": "Peanut butter, smooth style", "serving_amount": 2, "serving_unit": "tbsp", "serving_g": 32,
          "label_text": "2 tbsp (32 g)", "kcal": 190, "carbs": 7, "protein": 7, "fat": 16}
PB_OWN = {"name": "Peanut Butter", "serving_amount": 2, "serving_unit": "tbsp", "serving_g": 32, "kcal": 190, "carbs": 7, "protein": 7, "fat": 16}
BUTTER_OWN = {"name": "Butter", "serving_amount": 1, "serving_unit": "tbsp", "serving_g": 14, "kcal": 102, "carbs": 0, "protein": 0.1, "fat": 11.5}


def url(m):
    return f"/api/recipes/{m['id']}/match-search"


def search(env, m, rows=None, **body):
    ids = rows or [i["id"] for i in m["items"]]
    return env["c"].post(url(m), json={"item_ids": ids, **body})


def own(env, data, favorite=True):
    f = env["c"].post("/api/foods", json=data).json()
    if favorite:
        env["c"].post(f"/api/favorites/{f['id']}")
    return f


def no_claude(env):
    assert env["requests"] == [] and usage_count() == 0


# ---------- scoring ----------

@pytest.mark.parametrize("query,name,expect", [
    ("butter", "Butter", (2, 1.0)), ("butter", "Butter, salted", (2, 1.0)), ("Butter", "BUTTER", (2, 1.0)),
    ("eggs", "Egg", (2, 1.0)), ("tomatoes", "Tomato, raw", (2, 1.0)), ("berries", "Berry", (2, 1.0)),
    ("butter", "Peanut butter", (1, 0.8)), ("butter", "Peanut butter, smooth style", (1, 0.8)),
    ("salted butter", "Butter, salted", (2, 1.0)), ("olive oil", "Extra virgin olive oil", (1, 0.8)),
    ("unsalted butter", "Butter", (0, 0.7)), ("butter", "Margarine", None), ("", "Butter", None), ("butter", "", None),
    ("brown sugar", "Sugar", (0, 0.7)), ("brown sugar", "Brown rice", (0, 0.5)), ("a", "Banana", None),
])
def test_name_score(query, name, expect):
    got = recipe_ai.name_score(query, name)
    assert (got is None and expect is None) or (got[0] == expect[0] and got[1] == pytest.approx(expect[1], abs=0.01))


def test_pick_best_prefers_the_plain_food_over_a_longer_name():
    peanut = {"name": "Peanut Butter", "id": 1}
    butter = {"name": "Butter", "id": 2}
    assert recipe_ai.pick_best("butter", [(peanut, True), (butter, False)])[0] is butter  # exact beats my own partial
    assert recipe_ai.pick_best("butter", [(peanut, False), (butter, False)])[0] is butter
    assert recipe_ai.pick_best("butter", [(butter, False), (peanut, False)])[0] is butter
    assert recipe_ai.pick_best("peanut butter", [(butter, False), (peanut, False)])[0] is peanut


def test_pick_best_ties_go_to_my_foods_then_the_shorter_name_then_the_earlier_one():
    mine, other = {"name": "Butter", "id": 1}, {"name": "Butter, salted", "id": 2}
    assert recipe_ai.pick_best("butter", [(other, False), (mine, True)])[0] is mine
    short, long_ = {"name": "Flour"}, {"name": "All purpose flour"}
    got = recipe_ai.pick_best("flour", [(long_, False), (short, False)])
    assert got[0] is short  # exact beats partial
    first, second = {"name": "Egg", "n": 1}, {"name": "Egg", "n": 2}
    assert recipe_ai.pick_best("egg", [(first, False), (second, False)])[0] is first
    assert recipe_ai.pick_best("egg", [({"name": "Milk"}, True)]) is None
    assert recipe_ai.pick_best("", [(first, False)]) is None


# ---------- the route ----------

def test_butter_does_not_pick_peanut_butter(env):
    own(env, PB_OWN)  # a favorite
    env["fdc"]["butter"] = [PB_FDC, BUTTER_FDC]
    env["off"]["butter"] = [BUTTER_OFF]
    m = saved_recipe(env, [{"amount": 2, "unit": "tbsp", "name": "butter"}])
    p = search(env, m).json()["proposals"][0]
    assert p["kind"] == "candidate" and p["food"]["name"] == "Butter, salted" and p["food"]["source"] == "fdc"  # USDA first on a tie
    assert p["food"]["id"] and p["method"] == "search" and (p["amount"], p["unit"], p["check"]) == (2, "tbsp", False)
    assert p["preview"]["kcal"] == 200 and p["grams"] == 28 and p["note"] == "Same name in USDA"
    no_claude(env)


def test_own_foods_win_a_tie_and_skip_the_network(env):
    own(env, PB_OWN)
    mine = own(env, BUTTER_OWN)
    env["fdc"]["butter"] = [BUTTER_FDC]
    m = saved_recipe(env, [{"amount": 1, "unit": "tbsp", "name": "butter"}])
    p = search(env, m).json()["proposals"][0]
    assert p["food"]["id"] == mine["id"] and p["note"] == "Same name in your foods"
    assert env["searches"] == []  # an exact name among my own foods needs no lookup
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM foods WHERE source='fdc'").fetchone()[0] == 0


def test_own_means_favorites_past_foods_and_foods_i_made_but_not_hidden_or_someone_elses(env):
    fav = own(env, {**BUTTER_OWN, "name": "Favorite Butter"})
    made = own(env, {**BUTTER_OWN, "name": "Made Butter"}, favorite=False)
    past = env["b"].post("/api/foods", json={**BUTTER_OWN, "name": "Past Butter"}).json()
    env["c"].post("/api/entries", json={"food_id": past["id"], "amount": 1, "unit": "tbsp"})
    hidden = env["b"].post("/api/foods", json={**BUTTER_OWN, "name": "Hidden Butter"}).json()
    env["c"].post("/api/entries", json={"food_id": hidden["id"], "amount": 1, "unit": "tbsp"})
    with db.conn() as c:
        c.execute("INSERT INTO hidden_foods(user_id, food_id) VALUES (1, ?)", (hidden["id"],))
    theirs = env["b"].post("/api/foods", json={**BUTTER_OWN, "name": "Their Butter"}).json()
    names = {f["id"] for f in recipe_ai.own_foods(1)}
    assert names == {fav["id"], made["id"], past["id"]} and theirs["id"] not in names and hidden["id"] not in names
    assert {f["id"] for f in recipe_ai.own_foods(2)} >= {past["id"], theirs["id"]}
    assert fav["id"] not in {f["id"] for f in recipe_ai.own_foods(2)}


def test_no_candidate_stays_unmatched_with_a_note(env):
    m = saved_recipe(env, [{"amount": 1, "name": "dragonfruit"}, {"name": ""} if False else {"name": "boom"}])
    r = search(env, m)
    assert r.status_code == 200
    p = r.json()["proposals"]
    assert [x["kind"] for x in p] == ["none", "none"]
    assert p[0]["food"] is None and p[0]["note"] == "No match found." and p[0]["preview"] is None and p[0]["amount"] is None
    assert env["c"].get(f"/api/meals/{m['id']}").json()["matched"] == 0
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM foods").fetchone()[0] == 0  # nothing saved for a row without a match
    no_claude(env)


def test_a_candidate_that_shares_no_word_is_not_picked(env):
    env["fdc"]["flour"] = [{**FLOUR, "name": "Cornstarch"}]
    m = saved_recipe(env, [{"amount": 1, "unit": "cup", "name": "flour"}])
    assert search(env, m).json()["proposals"][0]["kind"] == "none"


def test_source_filter(env):
    own(env, {**BUTTER_OWN, "name": "Butter"})
    env["fdc"]["butter"] = [BUTTER_FDC]
    env["off"]["butter"] = [BUTTER_OFF]
    m = saved_recipe(env, [{"amount": 1, "unit": "tbsp", "name": "salted butter"}])
    env["fdc"]["salted butter"] = [BUTTER_FDC]
    env["off"]["salted butter"] = [{**BUTTER_OFF, "name": "Salted Butter", "source_id": "b3"}]
    p = search(env, m, source="off").json()["proposals"][0]
    assert p["food"]["source"] == "off" and p["food"]["name"] == "Salted Butter"
    assert [s[0] for s in env["searches"]] == ["off"]  # USDA is not asked
    env["searches"].clear()
    p = search(env, m, source="fdc").json()["proposals"][0]
    assert p["food"]["source"] == "fdc" and [s[0] for s in env["searches"]] == ["fdc"]
    env["searches"].clear()
    p = search(env, m, source="all").json()["proposals"][0]
    assert {s[0] for s in env["searches"]} == {"fdc", "off"} and p["food"]["name"] in ("Butter, salted", "Salted Butter")
    # my own custom Butter is not an off or fdc food, so a source filter leaves it out
    m2 = saved_recipe(env, [{"amount": 1, "unit": "tbsp", "name": "butter"}])
    assert search(env, m2, source="fdc").json()["proposals"][0]["food"]["source"] == "fdc"
    assert search(env, m2).json()["proposals"][0]["food"]["source"] == "custom"
    assert search(env, m2, source="nope").status_code == 400
    no_claude(env)


def test_amount_comes_from_the_recipe_line_and_a_bad_conversion_is_flagged(env):
    env["fdc"]["flour"] = [FLOUR]
    env["off"]["egg"] = [EGG_OFF]
    m = saved_recipe(env, [{"amount": 1.5, "unit": "cup", "name": "flour"}, {"amount": 2, "name": "egg"},
                           {"amount": 3, "unit": "pinch", "name": "flour"}, {"name": "flour"}])
    p = search(env, m).json()["proposals"]
    assert [(x["amount"], x["unit"], x["check"]) for x in p] == [(1.5, "cup", False), (2, "egg", False), (3, "pinch", False), (1, "cup", True)]
    assert "label serving" in p[3]["warnings"][0] and p[0]["grams"] == 187.5
    r = env["c"].patch(f"/api/meals/{m['id']}/items", json={"items": [
        {"id": m["items"][0]["id"], "food_id": p[0]["food"]["id"], "amount": p[0]["amount"], "unit": p[0]["unit"]},
        {"id": m["items"][2]["id"], "food_id": p[2]["food"]["id"], "amount": p[2]["amount"], "unit": p[2]["unit"], "check": True}]})
    assert r.status_code == 200 and (r.json()["matched"], r.json()["checks"]) == (1, 1)  # accepted like a Claude proposal


def test_works_without_claude_and_never_calls_it(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("AI_ALLOW_RECIPE", "0")
    env["fdc"]["flour"] = [FLOUR]
    m = saved_recipe(env)
    assert env["c"].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [m["items"][0]["id"]]}).status_code in (403, 503)
    r = search(env, m)
    assert r.status_code == 200 and r.json()["proposals"][0]["food"]["name"] == "Wheat flour"
    assert set(r.json()) == {"proposals", "method", "rate_limited"}  # no usage or cost fields
    assert r.json()["rate_limited"] is False
    no_claude(env)


def test_same_ingredient_is_looked_up_once(env):
    env["fdc"]["flour"] = [FLOUR]
    m = saved_recipe(env, [{"amount": 1, "unit": "cup", "name": "flour"}, {"amount": 2, "unit": "cup", "name": "flour"}])
    p = search(env, m).json()["proposals"]
    assert p[0]["food"]["id"] == p[1]["food"]["id"] and [s for s in env["searches"] if s[0] == "fdc"] == [("fdc", "flour", 5)]


@pytest.mark.parametrize("body", [None, {}, {"item_ids": []}, {"item_ids": "1"}, {"item_ids": [1], "x": 1}, {"item_ids": ["a"]},
                                  {"item_ids": [1], "source": "ai"}, {"item_ids": list(range(1, 42))}])
def test_validation(env, body):
    m = saved_recipe(env)
    assert env["c"].post(url(m), json=body).status_code == 400
    no_claude(env)


def test_up_to_40_rows_in_one_request_and_ownership(env):
    m = saved_recipe(env, [{"name": f"thing {i}"} for i in range(40)])
    ids = [i["id"] for i in m["items"]]
    r = search(env, m, ids)
    assert r.status_code == 200 and len(r.json()["proposals"]) == 40
    assert search(env, m, ids + [ids[-1] + 1000]).status_code == 400  # 41
    assert env["b"].post(url(m), json={"item_ids": ids[:1]}).status_code == 404
    other = saved_recipe(env)
    assert search(env, m, [other["items"][0]["id"]]).status_code == 404
    assert search(env, {"id": 9999}, [1]).status_code == 404
    assert recipe_ai.SEARCH_MAX_ROWS == 40 and recipe_ai.MAX_ROWS >= 40


def test_search_proposals_use_the_row_text_when_there_is_no_name(env):
    env["fdc"]["flour"] = [FLOUR]
    m = env["c"].post("/api/meals/import", json={"name": "R", "ingredients": [{"name": "flour"}]}).json()
    with db.conn() as c:
        c.execute("UPDATE meal_items SET src_name=NULL, src_text='flour' WHERE id=?", (m["items"][0]["id"],))
    assert search(env, m).json()["proposals"][0]["food"]["name"] == "Wheat flour"


def test_usda_rate_limit_stops_usda_and_marks_skipped_rows(env, monkeypatch):
    from app import lookup
    calls = []

    async def limited(q, limit=8, state=None):
        calls.append(q)
        if state is not None:
            state["limited"] = True
        return []

    monkeypatch.setattr(lookup, "search", limited)
    env["off"]["egg"] = [EGG_OFF]
    rows = [{"amount": 1, "unit": "cup", "name": "flour"}, {"amount": 2, "name": "egg"}] + [{"name": f"thing {i}"} for i in range(10)]
    m = saved_recipe(env, rows)
    r = search(env, m).json()
    assert r["rate_limited"] is True
    assert len(calls) <= recipe_ai.SEARCH_CONCURRENCY  # after the 429 the rows still waiting never ask USDA
    p = r["proposals"]
    assert all(x["skipped"] for x in p) and p[0]["note"] == "Not searched." and p[1]["food"]["name"]  # Open Food Facts still answers
    no_claude(env)


def test_no_rate_limit_means_no_skipped_rows(env):
    env["fdc"]["flour"] = [FLOUR]
    m = saved_recipe(env)
    r = search(env, m).json()
    assert r["rate_limited"] is False and not any("skipped" in x for x in r["proposals"])
