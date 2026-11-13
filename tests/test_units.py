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
    assert "piece" not in by_unit(BREAD)  # not offered, but piece is a plain count of the label's word
    assert servings_for(BREAD, 2, "piece") == {"servings": 2, "estimated": False}
    assert units.grams(BREAD, 2, "piece") == 68
    assert units.grams(BREAD, 2, "clove") is None and units.grams(BREAD, 2, "shell") is None  # another word has no known weight


def test_count_label_without_grams_is_count_only():
    f = food(1, "cookie")
    assert [u["unit"] for u in available_units(f)] == ["cookie", "serving", "pct", "count"]
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
    assert [u["unit"] for u in available_units(f)] == ["slice", "serving", "pct", "count"]
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
    assert [u["unit"] for u in available_units(f2)] == ["serving", "pct"]  # a serving label knows no count weight
    assert servings_for(f2, 1, "serving")["servings"] == 0.5  # label says 2 servings


def test_pct_and_serving_not_flagged_when_conversions_are_estimates():
    for u in available_units(OZ_ONLY):
        assert u["estimated"] is (u["unit"] in ("ml", "floz", "cup", "tbsp", "tsp", "l"))
    assert servings_for(OZ_ONLY, 50, "pct")["estimated"] is False


# ---------- match_amount and grams (Match Ingredients picks a food without the amount screen) ----------

FLOUR_G = {"serving_amount": 30, "serving_unit": "g", "kcal": 110, "carbs": 23, "protein": 3, "fat": 0}
FLOUR_CUP = {"serving_amount": 1, "serving_unit": "cup", "serving_g": 125, "kcal": 455, "carbs": 95, "protein": 13, "fat": 1}
BUTTER = {"serving_amount": 1, "serving_unit": "tbsp", "serving_g": 14, "kcal": 100, "carbs": 0, "protein": 0, "fat": 11}
MILK_ML = {"serving_amount": 240, "serving_unit": "ml", "serving_g": 248, "kcal": 120, "carbs": 12, "protein": 8, "fat": 5}
EGG = {"serving_amount": 1, "serving_unit": "egg", "serving_g": 50, "kcal": 72, "carbs": 0, "protein": 6, "fat": 5}
CHEESE = {"serving_amount": 28, "serving_unit": "g", "kcal": 110, "carbs": 1, "protein": 7, "fat": 9}


def test_match_amount_same_unit_and_same_family():
    assert units.match_amount(BUTTER, 2, "tbsp") == {"amount": 2, "unit": "tbsp", "check": False}
    assert units.match_amount(FLOUR_CUP, 1, "cups") == {"amount": 1, "unit": "cup", "check": False}
    assert units.match_amount(CHEESE, 4, "oz") == {"amount": 4, "unit": "oz", "check": False}  # weight to weight
    assert units.match_amount(MILK_ML, 1, "cup") == {"amount": 1, "unit": "cup", "check": False}  # volume to volume
    assert units.match_amount(FLOUR_CUP, 250, "grams") == {"amount": 250, "unit": "g", "check": False}  # through serving_g


def test_match_amount_counts():
    assert units.match_amount(EGG, 2, None) == {"amount": 2, "unit": "egg", "check": False}
    assert units.match_amount(EGG, 3, "eggs") == {"amount": 3, "unit": "egg", "check": False}
    assert units.match_amount(EGG, 2, "large") == {"amount": 2, "unit": "egg", "check": False}
    no_weight = {"amount": 28, "unit": "g", "check": True, "reason": "no_weight"}  # never label servings (issue #45)
    assert units.match_amount(CHEESE, 2, None) == no_weight
    assert units.match_amount(CHEESE, 1, "piece") == no_weight


def test_match_amount_uses_an_estimated_unit_and_says_so():
    # a cup of a food known only by weight: the picker offers cup (1 g per ml guess), so the line's amount is used, flagged
    assert units.match_amount(FLOUR_G, 1, "cup") == {"amount": 1, "unit": "cup", "check": False, "estimated": True}
    assert units.match_amount(FLOUR_G, 2, "tbsp") == {"amount": 2, "unit": "tbsp", "check": False, "estimated": True}
    assert "estimated" not in units.match_amount(FLOUR_CUP, 1, "cup")  # exact conversions carry no flag
    assert units.scale(FLOUR_G, 1, "cup")["estimated"] is True  # the same math the picker uses


def test_match_amount_needs_a_check_when_the_unit_is_unreachable():
    slice_only = food(2, "slice")  # no weight, no volume
    assert units.match_amount(slice_only, 1, "cup") == {"amount": 2, "unit": "slice", "check": True, "reason": "no_convert"}
    assert units.match_amount(slice_only, 1, "g") == {"amount": 2, "unit": "slice", "check": True, "reason": "no_convert"}
    # a package or fuzzy unit on a measure label has no known weight
    assert units.match_amount(FLOUR_CUP, 1, "can") == {"amount": 1, "unit": "cup", "check": True, "reason": "no_size"}  # a package
    assert units.match_amount(BUTTER, 3, "Pinch") == {"amount": 1, "unit": "tbsp", "check": True, "reason": "no_weight"}


@pytest.mark.parametrize("amount", [None, 0, -1, "x", float("nan")])
def test_match_amount_without_an_amount(amount):
    assert units.match_amount(BUTTER, amount, "tbsp") is None


def test_grams():
    assert units.grams(BUTTER, 2, "tbsp") == 28
    assert units.grams(FLOUR_CUP, 0.5, "cup") == 62.5
    assert units.grams(CHEESE, 4, "oz") == 113.4
    assert units.grams(CHEESE, 30, "g") is None  # already grams
    assert units.grams(FLOUR_G, 1, "cup") is None  # only an estimate
    assert units.grams(BUTTER, 1, "can") is None
    assert units.grams({"serving_amount": 1, "serving_unit": "egg", "kcal": 1, "carbs": 0, "protein": 0, "fat": 0}, 2, "egg") is None


# ---------- default_pick: the package's own serving ----------

@pytest.mark.parametrize("f,expected", [
    (food(30, "g"), (30, "g")),
    (food(1, "cup", g=125), (1, "cup")),
    (food(2, "slice", g=68), (2, "slice")),
    (food(2, "tbsp", g=30), (2, "tbsp")),
    (food(1, "serving", g=30), (30, "g")),          # "1 serving (30 g)": start at the weight
    (food(1, "serving", ml=240), (240, "ml")),
    (food(1, "serving", g=30, ml=28), (30, "g")),
    (food(1, "serving"), (1, "serving")),           # nothing better on the package
])
def test_default_pick_is_the_package_serving(f, expected):
    assert units.default_pick(f) == expected
    assert "serving" in by_unit(f)                  # serving stays a unit


# ---------- typical density by food name (used only when the label has no ml) ----------

CUP = units.VOLUME["cup"]


def cup_grams(f):
    """Grams in one US cup of the food, through servings (same math the picker and recipes use)."""
    s = units.servings_for(f, 1, "cup")
    return s["servings"] * units._profile(f)[2]


@pytest.mark.parametrize("name,grams", [
    ("All Purpose Flour", 125), ("Wheat flour, white, all-purpose", 125), ("Bread Flour", 127), ("Whole Wheat Flour", 120),
    ("Granulated Sugar", 200), ("Brown Sugar", 213), ("Powdered Sugar", 120), ("Butter, salted", 227), ("Honey", 340),
    ("Milk, whole", 245), ("Water", 237), ("Rolled Oats", 90), ("Rice, white, long-grain, raw", 185), ("Cocoa Powder", 85),
    ("Table Salt", 288), ("Baking Powder", 192), ("Peanut Butter", 258),
])
def test_weight_only_food_uses_its_typical_cup_weight(name, grams):
    f = food(30, "g", name=name)
    s = units.servings_for(f, 1, "cup")
    assert s["estimated"] is True                       # still an estimate, just a close one
    assert cup_grams(f) == pytest.approx(grams, rel=1e-6)
    assert by_unit(f)["cup"]["estimated"] is True


def test_flour_sugar_butter_cups_scale_nutrition_by_the_better_density():
    flour = food(30, "g", name="All Purpose Flour", kcal=110)
    assert units.scale(flour, 1, "cup")["kcal"] == pytest.approx(110 * 125 / 30)       # was 110 * 236.588 / 30
    sugar = food(4, "g", name="Granulated Sugar", kcal=15)
    assert units.scale(sugar, 1, "cup")["kcal"] == pytest.approx(15 * 200 / 4)
    butter = food(14, "g", name="Unsalted Butter", kcal=100)
    assert units.scale(butter, 1, "cup")["kcal"] == pytest.approx(100 * 227 / 14)
    assert units.scale(butter, 1, "tbsp")["kcal"] == pytest.approx(100 * 227 / 16 / 14, rel=1e-4)   # 16 tbsp to the cup


def test_volume_label_without_grams_uses_the_density_too():
    flour = food(1, "cup", name="Flour")
    assert by_unit(flour)["g"]["default_amount"] == pytest.approx(125, abs=0.01) and by_unit(flour)["g"]["estimated"] is True
    assert units.servings_for(flour, 250, "g")["servings"] == pytest.approx(2)


def test_unmatched_name_keeps_one_gram_per_ml():
    f = food(30, "g", name="Mystery Powder")
    assert units.density(f) is None
    assert cup_grams(f) == pytest.approx(CUP)
    assert units.servings_for(f, 1, "cup") == {"servings": pytest.approx(CUP / 30), "estimated": True}


@pytest.mark.parametrize("name", ["Butter Cookies", "Peanut Butter Cups", "Chocolate Milk", "Rice, cooked", "Sugar Snap Peas",
                                  "Salted Peanuts", "Rice Flour", "Tuna in oil", "Almond Milk", ""])
def test_lookalike_names_do_not_match(name):
    if name == "Peanut Butter Cups":
        assert units.density(food(30, "g", name=name)) == pytest.approx(258 / CUP)  # peanut butter is a keyword, the cups are close enough
        return
    assert units.density(food(30, "g", name=name)) is None


def test_label_ml_takes_priority_over_the_keyword_density():
    f = food(30, "g", ml=60, name="All Purpose Flour")          # the label itself says 30 g is 60 ml
    s = units.servings_for(f, 1, "cup")
    assert s["estimated"] is False
    assert s["servings"] == pytest.approx(CUP / 60)
    assert by_unit(f)["cup"]["estimated"] is False
    both = food(1, "cup", g=100, name="All Purpose Flour")        # label grams win for a volume label
    assert units.servings_for(both, 100, "g") == {"servings": pytest.approx(1), "estimated": False}


def test_count_unit_food_with_grams_only_uses_the_density():
    f = food(1, "slice", g=30, name="Rolled Oats")
    assert units.servings_for(f, 90, "g")["servings"] == pytest.approx(3)
    assert units.servings_for(f, 1, "cup")["servings"] == pytest.approx(3)  # 90 g per cup
    assert units.servings_for(f, 1, "cup")["estimated"] is True


def test_match_amount_for_a_cup_of_flour_is_estimated_with_the_better_density():
    flour = food(30, "g", name="All Purpose Flour")
    assert units.match_amount(flour, 1, "cup") == {"amount": 1, "unit": "cup", "check": False, "estimated": True}


@pytest.mark.parametrize("text,amount,rest", [
    ("1 ½ tablespoons olive oil", 1.5, "tablespoons olive oil"), ("1½ cups flour", 1.5, "cups flour"),
    ("¾ tsp salt", 0.75, "tsp salt"), ("1-1/2 cups sugar", 1.5, "cups sugar"), ("2-3 cloves garlic", 2.5, "cloves garlic"),
    ("1/2 cup (120 ml) milk", 0.5, "cup (120 ml) milk"), ("1 1/2 cups flour", 1.5, "cups flour"), ("⅓ cup rice", 1 / 3, "cup rice"),
    ("⅛ tsp nutmeg", 0.125, "tsp nutmeg"), ("2 eggs", 2, "eggs")])
def test_lead_amount(text, amount, rest):
    got = units.lead_amount(text)
    assert got[0] == pytest.approx(amount) and got[1] == rest


@pytest.mark.parametrize("text", ["salt to taste", "pepper", "as needed", "olive oil, as needed"])
def test_lead_amount_none(text):
    assert units.lead_amount(text) is None


@pytest.mark.parametrize("word,unit", [("tablespoons", "tbsp"), ("teaspoons", "tsp"), ("cups", "cup"), ("ounces", "oz"), ("pounds", "lb"),
                                       ("grams", "g"), ("Tablespoon", "tbsp"), ("milliliters", "ml"), ("cloves", "clove")])
def test_plural_units(word, unit):
    assert units.known_unit(word) == unit and units.lead_unit(word + " flour") == unit
