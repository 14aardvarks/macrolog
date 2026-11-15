"""Recipe first (v77, issue #49): Save Recipe creates the recipe at once with every line unmatched (POST /api/meals/import, one
request), then each row is matched on the recipe screen with the existing routes: match-search for one row (the + button), PATCH
the row on Accept, the bulk PATCH for Accept N Suggested Matches. No new route; this pins the sequence the client now uses."""
from tests.test_recipe_ai import EGG_OFF, FLOUR, env  # noqa: F401
from tests.test_recipe_search import BUTTER_FDC

LINES = [
    {"text": "1 1/2 cups flour, sifted", "amount": 1.5, "unit": "cup", "name": "flour", "note": "sifted"},
    {"text": "1 (15 oz) can black beans", "amount": 1, "unit": "can", "name": "black beans", "note": "15 oz", "pkg_amount": 15, "pkg_unit": "oz"},
    {"text": "2 tbsp butter", "amount": 2, "unit": "tbsp", "name": "butter"},
    {"text": "salt, to taste", "amount": None, "unit": None, "name": "salt", "note": "to taste"},
]


def save(env):
    body = {"name": "Stew", "servings": 4, "ingredients": LINES, "steps": ["Mix.", "Cook."], "source_url": "https://example.com/stew"}
    r = env["c"].post("/api/meals/import", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_save_recipe_keeps_every_line_unmatched_with_its_parts(env):
    m = save(env)
    assert (m["name"], m["servings"], m["steps"], m["source_url"]) == ("Stew", 4, ["Mix.", "Cook."], "https://example.com/stew")
    assert (m["matched"], m["needed"], m["complete"], m["kcal"]) == (0, 4, False, 0)
    srcs = [i["src"] for i in m["items"]]
    assert [(s["amount"], s["unit"], s["name"], s["note"]) for s in srcs] == [(1.5, "cup", "flour", "sifted"), (1, "can", "black beans", "15 oz"),
                                                                            (2, "tbsp", "butter", None), (None, None, "salt", "to taste")]
    assert (srcs[1]["pkg_amount"], srcs[1]["pkg_unit"]) == (15, "oz")
    assert all(i["food"] is None and not i["skipped"] and i["kcal"] is None for i in m["items"])
    assert env["requests"] == []  # saving never asks Claude


def test_one_row_plus_then_accept_counts_only_that_row(env):
    env["fdc"]["butter"] = [BUTTER_FDC]
    m = save(env)
    butter = m["items"][2]
    r = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [butter["id"]]})
    assert r.status_code == 200, r.text
    (p,) = r.json()["proposals"]
    assert p["item_id"] == butter["id"] and p["food"]["name"] == "Butter, salted" and (p["amount"], p["unit"]) == (2, "tbsp")
    m2 = env["c"].patch(f"/api/meals/{m['id']}/items/{butter['id']}", json={"food_id": p["food"]["id"], "amount": p["amount"], "unit": p["unit"]}).json()
    assert (m2["matched"], m2["needed"], m2["complete"]) == (1, 4, False)
    assert m2["kcal"] == 200 and m2["per_serving"]["kcal"] == 50  # partial totals: the matched row only
    others = [i for i in m2["items"] if i["id"] != butter["id"]]
    assert all(i["food"] is None for i in others) and others[0]["src"]["note"] == "sifted"


def test_match_all_then_accept_all_in_one_bulk_patch(env):
    env["fdc"]["butter"] = [BUTTER_FDC]
    m = save(env)
    ids = [i["id"] for i in m["items"]]
    props = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": ids}).json()["proposals"]
    found = [p for p in props if p["food"]]
    assert {p["food"]["name"] for p in found} >= {"Butter, salted"}
    rows = [{"id": p["item_id"], "food_id": p["food"]["id"], "amount": p["amount"], "unit": p["unit"], **({"check": True} if p["check"] else {})} for p in found]
    m2 = env["c"].patch(f"/api/meals/{m['id']}/items", json={"items": rows}).json()
    assert m2["matched"] + m2["checks"] == len(found)
    assert any(i["src"]["name"] == "salt" and i["food"] is None for i in m2["items"])  # a row with no suggestion stays a line
