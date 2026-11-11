import pytest

from app import units
from app.units import available_units, parse_unit, scale, servings_for


def food(amount, unit, g=None, ml=None, **kw):
    f = {"name": "x", "serving_amount": amount, "serving_unit": unit, "serving_g": g,
         "serving_ml": ml, "label_text": "", "kcal": 100, "carbs": 20, "protein": 5, "fat": 2, "fiber": 3}
    f.update(kw)
    return f


BREAD = food(1, "slice", g=34, kcal=80, carbs=15, protein=3, fat=1, fiber=1)
HUMMUS = food(2, "tbsp", g=30, kcal=70, carbs=4, protein=2, fat=5, fiber=2)
MUSTARD = food(1, "tsp", g=5, kcal=0, carbs=0, protein=0, fat=0, fiber=0)
MILK = food(1, "cup", g=244, ml=240, kcal=120, carbs=12, protein=8, fat=5, fiber=0)
OZ_ONLY = food(2, "oz", kcal=100)
ML_ONLY = food(250, "ml", kcal=100)


def by_unit(f):
    return {u["unit"]: u for u in available_units(f)}


@pytest.mark.parametrize("text,expected", [
    ("Tbsp.", "tbsp"), ("tbsps", "tbsp"), ("tablespoon", "tbsp"), ("Tablespoons", "tbsp"), ("TBS", "tbsp"),
    ("tsp", "tsp"), ("teaspoons", "tsp"), ("tsp.", "tsp"),
    ("fl oz", "floz"), ("fl. oz.", "floz"), ("FL OZ", "floz"), ("floz", "floz"),
    ("fluid ounce", "floz"), ("fluid ounces", "floz"),
    ("oz", "oz"), ("ounces", "oz"), ("Oz.", "oz"), ("lb", "lb"), ("lbs", "lb"), ("pounds", "lb"),
    ("g", "g"), ("grams", "g"), ("Gram", "g"), ("kg", "kg"), ("kilograms", "kg"),
    ("ml", "ml"), ("mL", "ml"), ("milliliters", "ml"), ("l", "l"), ("liter", "l"), ("Litres", "l"),
    ("cup", "cup"), ("cups", "cup"), ("  Cups. ", "cup"),
    ("slices", "slice"), ("Slice", "slice"), ("pieces", "piece"), ("cookies", "cookie"),
    ("glasses", "glass"), ("crackers", "cracker"),
])
def test_parse_unit(text, expected):
    assert parse_unit(text) == expected


def test_parse_unit_empty():
    for bad in ("", "  ", None, "."):
        with pytest.raises(ValueError):
            parse_unit(bad)


def test_bread_slice():
    us = available_units(BREAD)
    assert us[0] == {"unit": "slice", "label": "slice", "step": 0.5, "default_amount": 1, "estimated": False}
    assert [u["unit"] for u in us][:5] == ["slice", "serving", "pct", "g", "oz"]
    assert by_unit(BREAD)["g"]["default_amount"] == 34
    assert servings_for(BREAD, 2, "slice") == {"servings": 2, "estimated": False}
    assert servings_for(BREAD, 68, "g")["servings"] == pytest.approx(2)
    assert servings_for(BREAD, 68, "g")["estimated"] is False
    assert servings_for(BREAD, 34, "grams")["servings"] == pytest.approx(1)


def test_bread_volume_is_estimated_via_one_g_per_ml():
    r = servings_for(BREAD, 34, "ml")
    assert r["servings"] == pytest.approx(1) and r["estimated"] is True
    assert by_unit(BREAD)["cup"]["estimated"] is True
    assert by_unit(BREAD)["g"]["estimated"] is False


def test_bread_other_count_word_unreachable():
    with pytest.raises(ValueError):
        servings_for(BREAD, 1, "piece")
    assert "piece" not in by_unit(BREAD)


def test_count_label_without_grams_is_count_only():
    f = food(1, "cookie")
    assert [u["unit"] for u in available_units(f)] == ["cookie", "serving", "pct"]
    assert servings_for(f, 3, "cookies")["servings"] == 3
    for u in ("g", "oz", "ml", "cup"):
        with pytest.raises(ValueError):
            servings_for(f, 1, u)


def test_hummus_tbsp_with_grams():
    us = available_units(HUMMUS)
    assert us[0]["unit"] == "tbsp" and us[0]["default_amount"] == 2 and us[0]["step"] == 0.5
    u = by_unit(HUMMUS)
    assert u["g"]["default_amount"] == 30 and not u["g"]["estimated"]
    assert u["tsp"]["default_amount"] == 6 and not u["tsp"]["estimated"]
    assert u["cup"]["default_amount"] == pytest.approx(0.125, abs=0.01)
    assert servings_for(HUMMUS, 1, "tbsp")["servings"] == pytest.approx(0.5)
    assert servings_for(HUMMUS, 15, "g")["servings"] == pytest.approx(0.5)
    assert servings_for(HUMMUS, 3, "tsp")["servings"] == pytest.approx(0.5, rel=1e-4)
    assert "slice" not in u


def test_hummus_mass_to_volume_uses_density_estimated_flag():
    # tbsp label with grams given: grams to tbsp is exact, no estimate
    assert servings_for(HUMMUS, 60, "g")["estimated"] is False
    assert servings_for(HUMMUS, 4, "tbsp")["estimated"] is False


def test_mustard_tsp():
    assert servings_for(MUSTARD, 5, "g")["servings"] == pytest.approx(1)
    assert servings_for(MUSTARD, 1, "tbsp")["servings"] == pytest.approx(3, rel=1e-4)
    assert by_unit(MUSTARD)["tbsp"]["default_amount"] == pytest.approx(0.33)


def test_milk_cup_and_floz():
    us = available_units(MILK)
    assert us[0]["unit"] == "cup" and us[0]["default_amount"] == 1
    u = by_unit(MILK)
    assert u["ml"]["default_amount"] == 236.59 or u["ml"]["default_amount"] == pytest.approx(236.59)
    assert u["floz"]["default_amount"] == pytest.approx(8, abs=0.01)
    assert not any(x["estimated"] for x in us)
    assert servings_for(MILK, 8, "floz")["servings"] == pytest.approx(1, abs=1e-4)
    assert servings_for(MILK, 16, "fl oz")["servings"] == pytest.approx(2, abs=1e-3)
    assert servings_for(MILK, 244, "g")["servings"] == pytest.approx(1)
    assert servings_for(MILK, 2, "cups")["servings"] == 2
    assert servings_for(MILK, 236.588, "ml")["servings"] == pytest.approx(1)


def test_milk_label_with_both_families_uses_label_unit_exactly():
    # the label says 1 cup, so ml conversion uses cup size, not the printed 240 ml
    assert servings_for(MILK, 1, "tbsp")["servings"] == pytest.approx(14.7868 / 236.588)


def test_floz_label_with_density_from_ml_and_g():
    f = food(8, "fl oz", g=244, ml=240)
    assert servings_for(f, 244, "g") == {"servings": pytest.approx(1), "estimated": False}
    assert servings_for(f, 1, "cup")["servings"] == pytest.approx(236.588 / (8 * 29.5735))


def test_oz_only_label():
    us = available_units(OZ_ONLY)
    assert us[0]["unit"] == "oz" and us[0]["default_amount"] == 2
    u = by_unit(OZ_ONLY)
    assert u["g"]["default_amount"] == pytest.approx(56.7) and not u["g"]["estimated"]
    assert u["lb"]["estimated"] is False
    assert u["ml"]["estimated"] is True and u["cup"]["estimated"] is True
    assert servings_for(OZ_ONLY, 4, "oz") == {"servings": 2, "estimated": False}
    assert servings_for(OZ_ONLY, 56.699, "g")["servings"] == pytest.approx(1)
    assert servings_for(OZ_ONLY, 1, "lb")["servings"] == pytest.approx(453.592 / 56.699)
    assert servings_for(OZ_ONLY, 56.699, "ml")["estimated"] is True


def test_ml_only_label_converts_to_grams_as_estimate():
    us = available_units(ML_ONLY)
    assert us[0] == {"unit": "ml", "label": "ml", "step": 5, "default_amount": 250, "estimated": False}
    u = by_unit(ML_ONLY)
    assert u["g"]["estimated"] is True and u["g"]["default_amount"] == 250
    assert u["oz"]["estimated"] is True
    assert u["floz"]["estimated"] is False and u["cup"]["estimated"] is False
    r = servings_for(ML_ONLY, 500, "g")
    assert r["servings"] == pytest.approx(2) and r["estimated"] is True
    assert servings_for(ML_ONLY, 1, "l")["estimated"] is False
    assert servings_for(ML_ONLY, 1, "l")["servings"] == pytest.approx(4)


def test_g_only_label():
    f = food(100, "g")
    u = by_unit(f)
    assert u["g"]["estimated"] is False and u["ml"]["estimated"] is True
    assert servings_for(f, 1, "kg")["servings"] == pytest.approx(10)
    assert servings_for(f, 100, "ml") == {"servings": pytest.approx(1), "estimated": True}


def test_count_label_with_only_ml():
    f = food(1, "can", ml=355)
    u = by_unit(f)
    assert u["ml"]["estimated"] is False and u["g"]["estimated"] is True
    assert servings_for(f, 355, "ml")["servings"] == pytest.approx(1)
    assert servings_for(f, 355, "g")["estimated"] is True


def test_unit_aliases_in_food_and_amount_calls():
    f = food(2, "Tbsp.", g=30)
    assert available_units(f)[0]["unit"] == "tbsp"
    assert servings_for(f, 30, "Grams")["servings"] == pytest.approx(1)
    f2 = food(1, "Slices", g=34)
    assert servings_for(f2, 1, "slice")["servings"] == 1


def test_label_unit_first_and_unique():
    for f in (BREAD, HUMMUS, MUSTARD, MILK, OZ_ONLY, ML_ONLY):
        us = available_units(f)
        names = [u["unit"] for u in us]
        assert names[0] == parse_unit(f["serving_unit"])
        assert len(names) == len(set(names))
        assert us[0]["default_amount"] == f["serving_amount"]
        for x in us:
            assert set(x) == {"unit", "label", "step", "default_amount", "estimated"}
            assert x["default_amount"] > 0


def test_steps():
    u = by_unit(MILK)
    assert [u[k]["step"] for k in ("ml", "floz", "cup", "tbsp", "tsp")] == [5, 0.5, 0.125, 0.5, 0.25]
    u = by_unit(OZ_ONLY)
    assert [u[k]["step"] for k in ("g", "kg", "oz", "lb")] == [5, 0.05, 0.25, 0.05]
    assert by_unit(ML_ONLY)["l"]["step"] == 0.05
    assert units.COUNT_STEP == 0.5
    assert u["oz"]["label"] == "oz" and by_unit(MILK)["floz"]["label"] == "fl oz"


def test_scale_macros():
    r = scale(BREAD, 2, "slice")
    assert r == {"servings": 2, "estimated": False, "kcal": 160, "carbs": 30, "protein": 6, "fat": 2, "fiber": 2}
    r = scale(HUMMUS, 1, "tbsp")
    assert r["kcal"] == pytest.approx(35) and r["fat"] == pytest.approx(2.5) and r["servings"] == pytest.approx(0.5)


def test_scale_estimated_flag_propagates():
    assert scale(ML_ONLY, 250, "g")["estimated"] is True
    assert scale(ML_ONLY, 250, "ml")["estimated"] is False


def test_scale_missing_nutrients():
    f = food(1, "slice", g=30, fiber=None)
    del f["protein"]
    f["fat"] = None
    r = scale(f, 2, "slice")
    assert r["fiber"] is None
    assert r["protein"] == 0 and r["fat"] == 0
    assert r["kcal"] == 200
    del f["fiber"]
    assert scale(f, 1, "slice")["fiber"] is None


@pytest.mark.parametrize("amount", [0, -1, -0.5, None, "abc", float("nan"), float("inf")])
def test_bad_amounts(amount):
    with pytest.raises(ValueError):
        servings_for(BREAD, amount, "slice")
    with pytest.raises(ValueError):
        scale(BREAD, amount, "g")


def test_bad_serving_amount():
    for bad in (0, -1, None):
        f = food(bad, "g")
        with pytest.raises(ValueError):
            servings_for(f, 1, "g")
        with pytest.raises(ValueError):
            available_units(f)


def test_zero_serving_g_or_ml_treated_as_missing():
    f = food(1, "slice", g=0, ml=0)
    assert [u["unit"] for u in available_units(f)] == ["slice", "serving", "pct"]
    f = food(1, "cup", g=0)
    assert by_unit(f)["g"]["estimated"] is True


def test_unreachable_unit_raises_message():
    with pytest.raises(ValueError, match="Cannot convert"):
        servings_for(food(1, "slice"), 1, "cup")


def test_fractional_and_large_amounts():
    assert servings_for(BREAD, 0.5, "slice")["servings"] == 0.5
    assert servings_for(HUMMUS, 1.25, "tbsp")["servings"] == pytest.approx(0.625)
    assert servings_for(MILK, 3.5, "cup")["servings"] == pytest.approx(3.5)
    assert servings_for(OZ_ONLY, 10000, "g")["servings"] > 100


def test_input_food_not_mutated():
    f = dict(BREAD)
    available_units(f)
    scale(f, 1, "g")
    assert f == BREAD


# ---------- serving and percent pseudo-units ----------

@pytest.mark.parametrize("text,expected", [
    ("serving", "serving"), ("Servings", "serving"), ("svg", "serving"), ("SVG.", "serving"),
    ("%", "pct"), ("pct", "pct"), ("Percent", "pct"), ("% of serving", "pct"),
])
def test_parse_pseudo_units(text, expected):
    assert parse_unit(text) == expected


@pytest.mark.parametrize("f", [BREAD, HUMMUS, MILK, OZ_ONLY, ML_ONLY, food(1, "cookie")])
def test_serving_and_pct_math_for_every_food(f):
    assert servings_for(f, 0.5, "serving") == {"servings": 0.5, "estimated": False}
    assert servings_for(f, 1.5, "servings") == {"servings": 1.5, "estimated": False}
    assert servings_for(f, 25, "pct") == {"servings": 0.25, "estimated": False}
    assert servings_for(f, 150, "%") == {"servings": 1.5, "estimated": False}
    s = scale(f, 25, "pct")
    assert s["kcal"] == pytest.approx(f["kcal"] * 0.25) and s["estimated"] is False
    assert scale(f, 0.5, "serving")["protein"] == pytest.approx(f["protein"] * 0.5)


def test_serving_pct_rejects_bad_amounts():
    for bad in (0, -1, "x", None, float("inf")):
        with pytest.raises(ValueError):
            servings_for(BREAD, bad, "pct")
        with pytest.raises(ValueError):
            servings_for(BREAD, bad, "serving")


def test_available_units_order_and_defaults():
    us = available_units(HUMMUS)
    assert [u["unit"] for u in us][:5] == ["tbsp", "serving", "pct", "g", "oz"]
    u = by_unit(HUMMUS)
    assert u["serving"] == {"unit": "serving", "label": "serving", "step": 0.25, "default_amount": 1, "estimated": False}
    assert u["pct"] == {"unit": "pct", "label": "% of serving", "step": 5, "default_amount": 100, "estimated": False}


def test_no_duplicates_when_label_unit_is_serving():
    f = food(1, "serving", g=50)
    us = [u["unit"] for u in available_units(f)]
    assert us[:3] == ["serving", "pct", "g"]
    assert len(us) == len(set(us))
    assert servings_for(f, 0.5, "serving")["servings"] == 0.5
    f2 = food(2, "servings")
    assert [u["unit"] for u in available_units(f2)] == ["serving", "pct"]
    assert servings_for(f2, 1, "serving")["servings"] == 0.5  # label says 2 servings


def test_pct_and_serving_not_flagged_when_conversions_are_estimates():
    for u in available_units(OZ_ONLY):
        assert u["estimated"] is (u["unit"] in ("ml", "floz", "cup", "tbsp", "tsp", "l"))
    assert servings_for(OZ_ONLY, 50, "pct")["estimated"] is False
