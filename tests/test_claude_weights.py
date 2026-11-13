"""Issue #45 step 7: Claude's unit weights and densities, asked in the same batched match request, checked in code and saved as
the user's own estimated food_units rows (source ai). Claude and the lookups are mocked."""
import pytest

from app import core, db, recipe_ai, units
from tests.test_recipe_ai import env, reply, saved_recipe, usage_count  # noqa: F401

ROOT = {"source": "fdc", "source_id": "r1", "name": "Mystery root", "serving_amount": 100, "serving_unit": "g", "label_text": "100 g",
        "kcal": 100, "carbs": 20, "protein": 2, "fat": 1}
CLOVE_LINE = {"text": "2 cloves mystery root", "amount": 2, "unit": "clove", "name": "mystery root"}
CUP_LINE = {"text": "1 cup mystery root", "amount": 1, "unit": "cup", "name": "mystery root"}


def answer(row=1, choice=1, amount=2, unit="clove", unit_grams=None, density=None, estimate=None):
    return {"row": row, "choice": choice, "amount": amount, "unit": unit, "estimate": estimate, "note": None,
            "unit_grams": unit_grams, "density_g_per_cup": density}


def run(env, lines, *answers, client="c"):
    env["fdc"]["mystery root"] = [ROOT]
    m = env[client].post("/api/meals/import", json={"name": "Root", "ingredients": lines}).json()
    env["reply"] = reply(recipe_ai.MATCH_TOOL_NAME, {"matches": list(answers)})
    r = env[client].post(f"/api/recipes/{m['id']}/match", json={"item_ids": [i["id"] for i in m["items"]]})
    return m, r


def ai_rows():
    with db.conn() as c:
        return [tuple(r) for r in c.execute("SELECT user_id, unit, grams, source, estimated FROM food_units WHERE source='ai' ORDER BY id")]


def test_schema_keeps_the_strict_union_limit():
    unions = 0

    def walk(node):
        nonlocal unions
        if isinstance(node, dict):
            if isinstance(node.get("type"), list) or "anyOf" in node:
                unions += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(recipe_ai.MATCH_TOOL["input_schema"])
    assert unions == 9 and unions <= 16
    item = recipe_ai.MATCH_TOOL["input_schema"]["properties"]["matches"]["items"]
    assert {"unit_grams", "density_g_per_cup"} <= set(item["required"])
    assert item["properties"]["unit_grams"]["anyOf"][0]["properties"]["confidence"]["enum"] == ["low", "medium", "high"]


def test_accepted_weight_is_saved_per_user_and_applied(env):
    m, r = run(env, [CLOVE_LINE], answer(unit_grams={"unit": "cloves", "grams": 5, "confidence": "medium"}))
    assert r.status_code == 200, r.text
    assert len(env["requests"]) == 1 and usage_count() == 1  # the same request, counted once
    text = env["requests"][0]["messages"][0]["content"][0]["text"]
    assert "weight needed: one clove" in text and "Never invent a brand" in text
    p = r.json()["proposals"][0]
    assert (p["amount"], p["unit"], p["check"], p["estimated"]) == (2, "clove", False, True)
    assert (p["weight_source"], p["estimate_source"], p["weight_note"], p["weight_grams"]) == ("ai", "claude", "Estimated by Claude", 10)
    assert p["preview"]["kcal"] == pytest.approx(10)
    assert ai_rows() == [(1, "clove", 5, "ai", 1)]
    # accepted: the recipe row says the same
    it = env["c"].patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}",
                        json={"food_id": p["food"]["id"], "amount": 2, "unit": "clove"}).json()["items"][0]
    assert (it["weight_source"], it["estimate_source"], it["weight_note"], it["weight_grams"], it["kcal"]) == ("ai", "claude", "Estimated by Claude", 10, 10)


def test_density_for_a_volume_line_of_a_weight_label(env):
    _, r = run(env, [CUP_LINE], answer(amount=1, unit="cup", density={"grams": 120, "confidence": "high"}))
    assert "density needed" in env["requests"][0]["messages"][0]["content"][0]["text"]
    p = r.json()["proposals"][0]
    assert (p["amount"], p["unit"], p["estimated"], p["estimate_source"], p["weight_source"], p["weight_grams"]) == (1, "cup", True, "claude", "ai", 120)
    assert ai_rows() == [(1, "cup", 120, "ai", 1)]


@pytest.mark.parametrize("ug", [{"unit": "clove", "grams": 0.01, "confidence": "high"}, {"unit": "clove", "grams": 9000, "confidence": "high"},
                                {"unit": "can", "grams": 5, "confidence": "high"}, {"unit": "clove", "grams": True, "confidence": "high"},
                                {"unit": "clove", "grams": "5", "confidence": "high"}, {"unit": "clove", "grams": 5, "confidence": "sure"},
                                {"unit": "clove", "grams": 5, "confidence": "low"}, "junk"])
def test_rejected_or_low_confidence_keeps_the_check(env, ug):
    _, r = run(env, [CLOVE_LINE], answer(unit_grams=ug))
    p = r.json()["proposals"][0]
    assert (p["check"], p["check_reason"], p["weight_source"], p["weight_grams"]) == (True, "no_weight", None, None)
    assert ai_rows() == []


@pytest.mark.parametrize("d", [{"grams": 10, "confidence": "high"}, {"grams": 500, "confidence": "high"}, {"grams": 120, "confidence": "low"}])
def test_rejected_density_keeps_the_guess(env, d):
    _, r = run(env, [CUP_LINE], answer(amount=1, unit="cup", density=d))
    p = r.json()["proposals"][0]
    assert (p["estimated"], p["estimate_source"], p["weight_source"]) == (True, "guess", None)
    assert ai_rows() == []


def test_users_own_weight_wins_and_is_never_overwritten(env):
    env["fdc"]["mystery root"] = [ROOT]
    with db.conn() as c:
        f = core.save_food(c, core.normalize_food(ROOT))
    env["c"].put(f"/api/foods/{f['id']}/units", json={"unit": "clove", "grams": 4})
    _, r = run(env, [CLOVE_LINE], answer(unit_grams={"unit": "clove", "grams": 5, "confidence": "high"}))
    p = r.json()["proposals"][0]
    assert (p["unit"], p["estimated"], p["weight_source"], p["weight_grams"]) == ("clove", False, "user", 8)
    assert ai_rows() == []
    assert recipe_ai.save_ai_weight(f["id"], 1, "clove", 5) is False  # never over a user row
    with db.conn() as c:
        core.save_unit_weight(c, f["id"], None, "can", 300, "fdc")
    assert recipe_ai.save_ai_weight(f["id"], 1, "can", 200) is False  # nor an exact source row


def test_claude_weights_are_per_user(env):
    run(env, [CLOVE_LINE], answer(unit_grams={"unit": "clove", "grams": 5, "confidence": "high"}))
    with db.conn() as c:
        food_id = c.execute("SELECT food_id FROM food_units WHERE source='ai'").fetchone()[0]
    mine = env["c"].get(f"/api/foods/{food_id}/units").json()["units"]
    assert [(u["unit"], u["grams"], u["source"]) for u in mine] == [("clove", 5, "ai")]
    assert env["b"].get(f"/api/foods/{food_id}/units").json()["units"] == []
    m = env["b"].post("/api/meals/import", json={"name": "B", "ingredients": [CLOVE_LINE]}).json()
    p = env["b"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [m["items"][0]["id"]]}).json()["proposals"][0]
    assert (p["check"], p["check_reason"]) == (True, "no_weight")


def test_search_never_asks_claude(env):
    env["fdc"]["mystery root"] = [ROOT]
    m = saved_recipe(env, [CLOVE_LINE, CUP_LINE])
    p = env["c"].post(f"/api/recipes/{m['id']}/match-search", json={"item_ids": [i["id"] for i in m["items"]]}).json()["proposals"]
    assert env["requests"] == [] and ai_rows() == [] and p[0]["check"] is True


def test_cap_reached_sends_nothing_and_saves_nothing(env, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "0")
    _, r = run(env, [CLOVE_LINE], answer(unit_grams={"unit": "clove", "grams": 5, "confidence": "high"}))
    assert r.status_code == 429 and env["requests"] == [] and ai_rows() == []


def test_estimate_food_gets_the_weight_in_grams(env):
    est = {"name": "Mystery root", "serving_text": "100 g", "serving_g": 100, "kcal": 80, "carbs": 18, "protein": 2, "fat": 0, "fiber": None}
    _, r = run(env, [CLOVE_LINE], answer(choice=None, estimate=est, unit_grams={"unit": "clove", "grams": 5, "confidence": "high"}))
    p = r.json()["proposals"][0]
    assert (p["kind"], p["amount"], p["unit"], p["estimated"], p["estimate_source"], p["weight_source"]) == ("estimate", 10, "g", True, "claude", "ai")
    assert ai_rows() == []  # nothing saved for a food that does not exist yet


def test_weight_hint_only_where_nothing_knows_the_weight():
    row = lambda **kw: {"src_amount": 2, "src_unit": "clove", "src_name": "garlic", "src_text": None, "item_pkg_amount": None, "item_pkg_unit": None, **kw}  # noqa: E731
    assert recipe_ai.weight_hint(row()) == ""  # a typical garlic clove is known
    assert recipe_ai.weight_hint(row(src_name="mystery root")) == "weight needed: one clove\n"
    assert recipe_ai.weight_hint(row(src_name="mystery root", item_pkg_amount=15, item_pkg_unit="oz")) == ""
    assert recipe_ai.weight_hint(row(src_unit="cup")) == "density needed\n"
    assert recipe_ai.weight_hint(row(src_amount=None)) == ""
    assert recipe_ai.weight_hint(row(src_unit=None, src_name="large eggs")) == ""


def test_bounds_helper():
    assert units.ai_number(5, 0.05, 5000) == 5 and units.ai_number(float("nan"), 0, 9) is None
    assert units.ai_number(float("inf"), 0, 9) is None and units.ai_number(None, 0, 9) is None


# ---------- step 8: the review preview, the tag's typed grams, recipe log parts ----------

def test_units_preview_before_matching(env):
    lines = [{"amount": 2, "unit": "clove", "name": "garlic"}, {"amount": 1, "unit": "can", "name": "black beans"},
             {"amount": 2, "unit": "clove", "name": "mystery root"}, {"amount": 1, "unit": "can", "name": "mystery root"},
             {"amount": 1, "unit": "cup", "name": "flour"}, {"name": "salt"}, {"amount": 2, "unit": "count", "name": "large eggs"},
             {"amount": 1, "unit": "can", "name": "beans", "pkg_amount": 15, "pkg_unit": "oz"}, "junk"]
    r = env["c"].post("/api/units/preview", json={"lines": lines})
    assert r.status_code == 200, r.text
    out = r.json()["lines"]
    assert out[0] == {"unit": "clove", "grams": 3, "total": 6, "source": "table", "estimated": True}
    assert out[1]["grams"] == 425 and out[1]["note"] == "Standard can size assumed"
    assert out[2] == {"reason": "no_weight", "unit": "clove"} and out[3] == {"reason": "no_size", "unit": "can"}
    assert out[4] == {} and out[5] == {} and out[8] == {}
    assert (out[6]["unit"], out[6]["grams"]) == ("count", 50)
    assert (out[7]["source"], out[7]["grams"], out[7]["estimated"]) == ("printed", 425.2, False)
    assert env["requests"] == []  # never Claude
    assert env["c"].post("/api/units/preview", json={"lines": [{}] * 101}).status_code == 400
    assert env["c"].post("/api/units/preview", json={"rows": []}).status_code == 400


def test_typed_grams_on_an_estimated_row_become_your_weight(env):
    m, r = run(env, [CLOVE_LINE, CUP_LINE], answer(unit_grams={"unit": "clove", "grams": 5, "confidence": "high"}),
               answer(row=2, amount=1, unit="cup", density={"grams": 120, "confidence": "high"}))
    p = r.json()["proposals"]
    url = f"/api/meals/{m['id']}/items/"
    i1, i2 = [i["id"] for i in m["items"]]
    fid = p[0]["food"]["id"]
    env["c"].patch(url + str(i1), json={"food_id": fid, "amount": 2, "unit": "clove"})
    env["c"].patch(url + str(i2), json={"food_id": fid, "amount": 1, "unit": "cup"})
    # the tag's grams: a match in g with remember, from the row's own amount (2 clove, 1 cup)
    env["c"].patch(url + str(i1), json={"food_id": fid, "amount": 8, "unit": "g", "remember": True})
    it = env["c"].patch(url + str(i2), json={"food_id": fid, "amount": 90, "unit": "g", "remember": True}).json()["items"]
    assert (it[0]["amount"], it[0]["unit"], it[0]["estimated"]) == (8, "g", False)
    got = {(u["unit"], u["grams"], u["source"]) for u in env["c"].get(f"/api/foods/{fid}/units").json()["units"]}
    assert got == {("clove", 4, "user"), ("cup", 90, "user")}


def test_recipe_log_parts_carry_the_estimated_weight(env):
    m, r = run(env, [CLOVE_LINE], answer(unit_grams={"unit": "clove", "grams": 5, "confidence": "high"}))
    p = r.json()["proposals"][0]
    env["c"].patch(f"/api/meals/{m['id']}/items/{m['items'][0]['id']}", json={"food_id": p["food"]["id"], "amount": 2, "unit": "clove"})
    gid = env["c"].post(f"/api/meals/{m['id']}/log", json={}).json()["entries"][0]["group_id"]
    part = env["c"].get(f"/api/entry-groups/{gid}").json()["parts"][0]
    assert (part["estimated"], part["estimate_source"], part["weight_source"], part["weight_note"], part["weight_grams"]) == (
        True, "claude", "ai", "Estimated by Claude", 10)
