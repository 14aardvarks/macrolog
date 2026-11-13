"""Missing energy: kJ conversion, alternate OFF fields, the estimate from macros, real zeros and older stored foods."""
import pytest

from app import core, db, lookup, units
from tests.test_core import BREAD, TODAY, a, b, env  # noqa: F401

FRUITOLA = {"carbohydrates_serving": 24, "proteins_serving": 8, "fat_serving": 1, "fiber_serving": 3.5}
EST = 4 * 8 + 4 * 20.5 + 2 * 3.5 + 9 * 1  # 130


def off(nutriments, **kw):
    p = {"code": "0073472001011", "product_name": "Fruitola Cinnamon", "serving_size": "1.5 cup (177 g)", "serving_quantity": 177,
         "nutriments": nutriments} | kw
    return lookup.off_food("0073472001011", p)


def with_macros(a, **kw):
    """Save a lookup style food straight to the table, the way search and scan do."""
    with db.conn() as c:
        return core.save_food(c, core.normalize_food({"source": "off", "source_id": "x1", "name": "Fruitola Cinnamon", "serving_amount": 1.5,
                                                     "serving_unit": "cup", "serving_g": 177, "carbs": 24, "protein": 8, "fat": 1, "fiber": 3.5,
                                                     "kcal": 0, **kw}))


# ---------- pure helpers ----------

def test_estimate_formula_and_fiber_floor():
    assert units.estimate_kcal(24, 8, 1, 3.5) == EST
    assert units.estimate_kcal(2, 0, 0, 5) == 10  # fiber larger than carbs: net carbs never negative
    assert units.estimate_kcal(None, None, None) is None


def test_resolve_cases():
    assert units.resolve_kcal(250, 24, 8, 1, 3.5) == (250, False)  # a real value always wins
    assert units.resolve_kcal(None, 24, 8, 1, 3.5) == (EST, True)
    assert units.resolve_kcal(0, 24, 8, 1, 3.5) == (EST, True)  # a 0 beside real macros is missing
    assert units.resolve_kcal(0, 0, 0, 0) == (0, False)  # all zeros: a real 0
    assert units.resolve_kcal(None, 0, 0, 0) == (0.0, False)
    assert units.resolve_kcal(0, 0.5, 0.2, 0) == (0, False)  # label rounded: tiny macros keep the 0
    assert units.resolve_kcal(None, None, None, None) == (None, False)


# ---------- lookup parsers ----------

def test_off_kj_only_is_converted():
    f = off({"energy_100g": 418.4, **{k.replace("_serving", "_100g"): v for k, v in FRUITOLA.items()}})
    assert f["kcal"] == pytest.approx(177, abs=0.1) and f["kcal_estimated"] is False  # 418.4 kJ = 100 kcal per 100 g, 177 g


def test_off_serving_kj_field_is_used():
    f = off({"energy_serving": 418.4, **FRUITOLA})
    assert f["kcal"] == pytest.approx(100, abs=0.01) and f["kcal_estimated"] is False


def test_off_kcal_zero_does_not_hide_kj():
    f = off({"energy-kcal_100g": 0, "energy_100g": 418.4, "carbohydrates_100g": 10})
    assert f["kcal"] == pytest.approx(177, abs=0.1) and f["kcal_estimated"] is False


def test_off_kj_named_field():
    f = off({"energy-kj_100g": 418.4, "carbohydrates_100g": 10})
    assert f["kcal"] == pytest.approx(177, abs=0.1) and not f["kcal_estimated"]


def test_off_missing_energy_with_macros_is_estimated():
    f = off(FRUITOLA)
    assert f["kcal"] == EST and f["kcal_estimated"] is True
    assert (f["carbs"], f["protein"], f["fat"], f["fiber"]) == (24, 8, 1, 3.5)


def test_off_energy_zero_with_macros_is_estimated():
    f = off({**FRUITOLA, "energy-kcal_serving": 0})
    assert f["kcal"] == EST and f["kcal_estimated"] is True


def test_off_real_values_never_replaced():
    f = off({**FRUITOLA, "energy-kcal_serving": 150})
    assert f["kcal"] == 150 and f["kcal_estimated"] is False


def test_off_real_zero_stays_zero():
    f = off({"energy-kcal_serving": 0, "carbohydrates_serving": 0, "proteins_serving": 0, "fat_serving": 0})
    assert f["kcal"] == 0 and f["kcal_estimated"] is False


def test_off_no_energy_and_no_macros_is_unusable():
    assert off({}) is None


def test_fdc_kj_only_and_macros_only():
    base = {"fdcId": 5, "description": "X", "servingSize": 100, "servingSizeUnit": "g"}
    kj = lookup.fdc_food({**base, "foodNutrients": [{"nutrientNumber": "268", "value": 418.4}, {"nutrientNumber": "205", "value": 10}]})
    assert kj["kcal"] == pytest.approx(100, abs=0.01) and kj["kcal_estimated"] is False
    macros = lookup.fdc_food({**base, "foodNutrients": [{"nutrientNumber": "205", "value": 24}, {"nutrientNumber": "203", "value": 8},
                                                       {"nutrientNumber": "204", "value": 1}, {"nutrientNumber": "291", "value": 3.5}]})
    assert macros["kcal"] == EST and macros["kcal_estimated"] is True
    assert lookup.fdc_food({**base, "foodNutrients": []}) is None


# ---------- stored foods and read time ----------

def test_lookup_estimate_is_stored_and_flagged(a):
    food = lookup.off_food("0073472001011", {"code": "0073472001011", "product_name": "Fruitola", "serving_size": "1 cup (177 g)",
                                             "serving_quantity": 177, "nutriments": FRUITOLA})
    with db.conn() as c:
        saved = core.save_food(c, core.normalize_food(food))
    assert saved["kcal"] == EST and saved["kcal_estimated"] is True
    assert a.get(f"/api/foods/{saved['id']}").json()["kcal_estimated"] is True


def test_older_zero_food_reads_as_estimated_without_changing_the_row(a):
    f = with_macros(a)
    assert f["kcal"] == EST and f["kcal_estimated"] is True
    with db.conn() as c:
        assert c.execute("SELECT kcal, kcal_estimated FROM foods WHERE id=?", (f["id"],)).fetchone()[:] == (0, 0)  # nothing rewritten


def test_real_zero_and_real_values_untouched(a):
    z = with_macros(a, source_id="z", carbs=0, protein=0, fat=0, fiber=None)
    assert z["kcal"] == 0 and z["kcal_estimated"] is False
    r = with_macros(a, source_id="r", kcal=150)
    assert r["kcal"] == 150 and r["kcal_estimated"] is False


def test_day_and_preview_use_the_estimate(a):
    f = with_macros(a)
    p = a.get("/api/preview", params={"food_id": f["id"], "amount": 1.5, "unit": "cup"}).json()
    assert p["kcal"] == EST and p["kcal_estimated"] is True
    e = a.post("/api/entries", json={"food_id": f["id"], "amount": 1.5, "unit": "cup", "day": TODAY, "meal": "breakfast"}).json()
    assert e["kcal"] == EST and e["kcal_estimated"] is True
    day = a.get("/api/day", params={"day": TODAY}).json()
    assert day["totals"]["kcal"] == EST and day["entries"][0]["kcal_estimated"] is True


def test_older_logged_zero_entry_reads_as_estimated_in_day_totals(a):
    f = with_macros(a)
    with db.conn() as c:  # an entry logged before estimates: kcal snapshot 0 beside real macros
        c.execute("INSERT INTO entries(user_id, day, meal, food_id, name, amount, unit, servings, kcal, carbs, protein, fat, fiber) "
                  "VALUES (1, ?, 'lunch', ?, 'Fruitola Cinnamon', 1.5, 'cup', 1, 0, 24, 8, 1, 3.5)", (TODAY, f["id"]))
    day = a.get("/api/day", params={"day": TODAY}).json()
    assert day["totals"]["kcal"] == EST and day["entries"][0]["kcal"] == EST and day["entries"][0]["kcal_estimated"] is True


def test_recipe_totals_use_the_estimate(a):
    f = with_macros(a)
    m = a.post("/api/meals", json={"name": "Bowl", "items": [{"food_id": f["id"], "amount": 1.5, "unit": "cup"}]}).json()
    assert m["totals"]["kcal"] == EST and m["kcal"] == EST and m["kcal_estimated"] is True
    assert m["items"][0]["kcal_estimated"] is True


# ---------- custom foods and edits ----------

def test_custom_blank_calories_are_estimated_then_cleared_by_an_edit(a):
    f = a.post("/api/foods", json={**BREAD, "kcal": None}).json()
    assert f["kcal"] == 4 * 4 + 4 * 14 + 2 * 3 + 9 * 1.5 and f["kcal_estimated"] is True
    same = a.patch(f"/api/foods/{f['id']}", json={"kcal": f["kcal"], "protein": 5}).json()  # untouched calories stay an estimate
    assert same["kcal_estimated"] is True and same["kcal"] == f["kcal"] + 4
    typed = a.patch(f"/api/foods/{f['id']}", json={"kcal": 99}).json()
    assert typed["kcal"] == 99 and typed["kcal_estimated"] is False
    again = a.patch(f"/api/foods/{f['id']}", json={"protein": 6}).json()
    assert again["kcal"] == 99 and again["kcal_estimated"] is False  # a typed value is never replaced


def test_custom_typed_zero_stays_zero(a):
    f = a.post("/api/foods", json={**BREAD, "kcal": 0}).json()
    assert f["kcal"] == 0 and f["kcal_estimated"] is False


def test_client_cannot_flag_a_custom_value_as_estimated(a):
    f = a.post("/api/foods", json={**BREAD, "kcal_estimated": True}).json()
    assert f["kcal"] == 90 and f["kcal_estimated"] is False


def test_migration_adds_the_columns_to_an_old_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    with db.conn() as c:
        db.init_shared(c)
        core.init(c)
        c.execute("ALTER TABLE foods DROP COLUMN kcal_estimated")
        c.execute("ALTER TABLE entries DROP COLUMN kcal_estimated")
    with db.conn() as c:
        core.init(c)
        for t in ("foods", "entries"):
            assert "kcal_estimated" in {r[1] for r in c.execute(f"PRAGMA table_info({t})")}


# ---------- refresh ----------

def test_refresh_replaces_an_estimate_with_the_real_value(a, monkeypatch):
    import httpx
    f = with_macros(a, source_id="3017620422003", barcode="3017620422003", serving_amount=15, serving_unit="g", serving_g=15,
                    carbs=8, protein=1, fat=4.5, fiber=None, kcal=0)
    assert f["kcal_estimated"] is True
    off_json = {"status": 1, "product": {"code": "3017620422003", "product_name": "Spread", "serving_size": "15 g", "serving_quantity": 15,
                                         "nutriments": {"energy-kcal_serving": 80, "carbohydrates_serving": 8, "proteins_serving": 1,
                                                        "fat_serving": 4.5}}}
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json=off_json)))
    r = a.post(f"/api/foods/{f['id']}/refresh-nutrients").json()
    assert "kcal" in r["filled"] and "calories" in r["message"]
    assert r["food"]["kcal"] == 80 and r["food"]["kcal_estimated"] is False
    with db.conn() as c:
        assert c.execute("SELECT kcal, kcal_estimated FROM foods WHERE id=?", (f["id"],)).fetchone()[:] == (80, 0)
    assert a.get(f"/api/foods/{f['id']}").json()["kcal"] == 80


def test_missing_nutrients_lists_a_food_with_missing_energy(a):
    f = with_macros(a, **{k: 1 for k in core.MICROS if k != "fiber"}, fiber=3.5)
    a.post("/api/entries", json={"food_id": f["id"], "amount": 1.5, "unit": "cup", "day": TODAY, "meal": "lunch"})
    assert a.get("/api/foods/missing-nutrients").json()["ids"] == [f["id"]]  # every micro is filled, only the energy is missing
    ok = with_macros(a, source_id="ok", kcal=150, **{k: 1 for k in core.MICROS if k != "fiber"}, fiber=3.5)
    a.post("/api/entries", json={"food_id": ok["id"], "amount": 1.5, "unit": "cup", "day": TODAY, "meal": "lunch"})
    assert a.get("/api/foods/missing-nutrients").json()["ids"] == [f["id"]]
