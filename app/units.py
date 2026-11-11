"""Unit parsing and conversion. Pure functions, standard library only.

Nutrients on a food are per label serving. Every conversion goes through
"servings": amount in some unit -> number of label servings.
"""
import math
import re

MASS = {"g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}
VOLUME = {"ml": 1.0, "l": 1000.0, "floz": 29.5735, "cup": 236.588, "tbsp": 14.7868, "tsp": 4.92892}
STEPS = {"g": 5, "kg": 0.05, "oz": 0.25, "lb": 0.05, "ml": 5, "l": 0.05,
         "floz": 0.5, "cup": 0.125, "tbsp": 0.5, "tsp": 0.25}
COUNT_STEP = 0.5
# Pseudo-units that work for every food: label servings, and percent of one label serving.
SERVING, PCT = "serving", "pct"
PSEUDO = (SERVING, PCT)
STEPS.update({SERVING: 0.25, PCT: 5})
LABELS = {"floz": "fl oz", SERVING: "serving", PCT: "% of serving"}
PSEUDO_DEFAULT = {SERVING: 1.0, PCT: 100.0}
# Display order for the non-label units offered in the picker.
ORDER = ["g", "oz", "lb", "kg", "ml", "floz", "cup", "tbsp", "tsp", "l"]

_ALIASES = {
    "g": "g", "gm": "g", "gram": "g", "gramme": "g",
    "kg": "kg", "kilo": "kg", "kilogram": "kg",
    "oz": "oz", "ounce": "oz",
    "lb": "lb", "pound": "lb",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml",
    "l": "l", "liter": "l", "litre": "l",
    "floz": "floz", "fl oz": "floz", "fluid ounce": "floz", "fluid oz": "floz", "fl ounce": "floz",
    "cup": "cup",
    "serving": "serving", "servings": "serving", "svg": "serving", "svgs": "serving",
    "%": PCT, "pct": PCT, "percent": PCT, "percentage": PCT,
    "tbsp": "tbsp", "tbs": "tbsp", "tbl": "tbsp", "tablespoon": "tbsp", "tablespoonful": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoonful": "tsp",
}


def _singular(word):
    if re.search(r"(ss|sh|ch|x|z)es$", word):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 2:
        return word[:-1]
    return word


def parse_unit(text):
    """Map free text to a canonical unit or a lowercase singular count word."""
    raw = str(text or "").strip().lower()
    if raw in ("%", "% of serving", "% of a serving", "percent of serving"):
        return PCT
    t = re.sub(r"[.,()]", " ", raw)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        raise ValueError("Unit is empty")
    if t in _ALIASES:
        return _ALIASES[t]
    # Singularize each word ("tablespoons", "fluid ounces", "fl ozs") and retry.
    s = " ".join(_singular(w) for w in t.split(" "))
    if s in _ALIASES:
        return _ALIASES[s]
    if t.replace(" ", "") in _ALIASES:  # "fl oz" written "floz", "f l oz"
        return _ALIASES[t.replace(" ", "")]
    return s


def _pos(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def _profile(food):
    """Return (label unit, label amount, grams, grams estimated, ml, ml estimated) per serving."""
    unit = parse_unit(food.get("serving_unit"))
    amount = _pos(food.get("serving_amount"))
    if amount is None:
        raise ValueError("Food has no valid serving_amount")
    sg, sml = _pos(food.get("serving_g")), _pos(food.get("serving_ml"))
    g = ge = ml = mle = None
    if unit in MASS:
        g, ge = amount * MASS[unit], False
        ml, mle = (sml, False) if sml else (g, True)  # 1 g per ml when no volume on the label
    elif unit in VOLUME:
        ml, mle = amount * VOLUME[unit], False
        g, ge = (sg, False) if sg else (ml, True)
    else:
        g, ml = sg, sml
        ge = mle = False
        if g and not ml:
            ml, mle = g, True
        elif ml and not g:
            g, ge = ml, True
    return unit, amount, g, bool(ge), ml, bool(mle)


def _convert(food, amount, unit):
    """Return (servings, estimated). Raises ValueError for bad amounts or unreachable units."""
    amount = _pos(amount)
    if amount is None:
        raise ValueError("Amount must be greater than zero")
    unit = parse_unit(unit)
    label_unit, label_amount, g, ge, ml, mle = _profile(food)
    if unit == label_unit:
        return amount / label_amount, False
    if unit == SERVING:
        return amount, False
    if unit == PCT:
        return amount / 100.0, False
    if unit in MASS and g:
        return amount * MASS[unit] / g, ge
    if unit in VOLUME and ml:
        return amount * VOLUME[unit] / ml, mle
    raise ValueError(f"Cannot convert {unit} for this food")


def servings_for(food, amount, unit):
    servings, estimated = _convert(food, amount, unit)
    return {"servings": servings, "estimated": estimated}


def available_units(food):
    """Label unit first (default = label amount), then every other reachable unit."""
    label_unit, label_amount, g, ge, ml, mle = _profile(food)

    def entry(unit, default, estimated):
        return {"unit": unit, "label": LABELS.get(unit, unit), "step": STEPS.get(unit, COUNT_STEP),
                "default_amount": default, "estimated": estimated}

    out = [entry(label_unit, label_amount, False)]
    for unit in PSEUDO:
        if unit != label_unit:
            out.append(entry(unit, PSEUDO_DEFAULT[unit], False))
    for unit in ORDER:
        if unit == label_unit:
            continue
        per, est = (g, ge) if unit in MASS else (ml, mle)
        if per:  # one serving expressed in this unit
            table = MASS if unit in MASS else VOLUME
            x = per / table[unit]
            out.append(entry(unit, round(x, 2) or float(f"{x:.2g}"), est))
    return out


def scale(food, amount, unit):
    servings, estimated = _convert(food, amount, unit)

    def val(key):
        v = food.get(key)
        return float(v) * servings if v is not None else None

    res = {"servings": servings, "estimated": estimated}
    for key in ("kcal", "carbs", "protein", "fat"):
        v = val(key)
        res[key] = v if v is not None else 0.0
    res["fiber"] = val("fiber")
    return res
