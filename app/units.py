"""Unit parsing and conversion. Pure functions, standard library only.

Nutrients on a food are per label serving. Every conversion goes through
"servings": amount in some unit -> number of label servings.
"""
import math
import re
import unicodedata

MASS = {"g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}
VOLUME = {"ml": 1.0, "l": 1000.0, "floz": 29.5735, "cup": 236.588, "tbsp": 14.7868, "tsp": 4.92892}
STEPS = {"g": 5, "kg": 0.05, "oz": 0.25, "lb": 0.05, "ml": 5, "l": 0.05,
         "floz": 0.5, "cup": 0.125, "tbsp": 0.5, "tsp": 0.25}
COUNT_STEP = 0.5
# Pseudo-units that work for every food: label servings, and percent of one label serving.
SERVING, PCT = "serving", "pct"
PSEUDO = (SERVING, PCT)
STEPS.update({SERVING: 0.25, PCT: 5})
# Count is a plain "this many of the thing" unit and BLANK is no unit at all (stored as ""). Both mean one label serving per 1 when the label
# is not a count word, else one of the label's count word (2 slice per serving on a "2 slice" label). Count is offered for every food, shown
# lowercase. A custom unit is any other typed word (pinch, can, clove, to taste): kept as typed (MAX_UNIT characters, no control characters)
# and treated like Count, never converted.
COUNT, BLANK = "count", ""
MAX_UNIT = 30
LABELS = {"floz": "fl oz", SERVING: "serving", PCT: "% of serving", COUNT: "count"}
PSEUDO_DEFAULT = {SERVING: 1.0, PCT: 100.0}
# Display order for the non-label units offered in the picker.
ORDER = ["g", "oz", "lb", "kg", "ml", "floz", "cup", "tbsp", "tsp", "l"]
KNOWN = {*MASS, *VOLUME, *PSEUDO, COUNT}

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


def clean_unit_text(text):
    """A typed unit with control characters dropped and spaces tidied. Raises ValueError past MAX_UNIT characters."""
    t = " ".join("".join(ch for ch in str(text or "") if unicodedata.category(ch)[0] != "C" or ch.isspace()).split())
    if len(t) > MAX_UNIT:
        raise ValueError(f"Unit must be {MAX_UNIT} characters or fewer")
    return t


def is_custom(unit):
    """True for a typed unit that is neither blank, count nor a measure the server knows (pinch, can, clove)."""
    return bool(unit) and unit not in KNOWN


def unit_or_blank(text):
    """The unit to store: no unit at all ("", None, "-", "none") is BLANK (""), a known unit or alias is its canonical name
    ("Cups" -> cup, "Count" -> count) and anything else is a custom unit kept as typed (trimmed, "Pinch" stays "Pinch")."""
    t = clean_unit_text(text)
    if t.lower() in ("", "-", "none"):
        return BLANK
    p = parse_unit(t)
    return p if p in KNOWN else t


def same_word(unit, label_unit):
    """A typed count word against the label's own (lowercase singular): "Slices" is the label's slice."""
    return bool(unit) and parse_unit(unit) == label_unit


def _pos(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


# ---------- typical density of common ingredients ----------
# Used ONLY when a food is known by weight (or by volume) on its label and the other family is missing: the old guess was 1 g per ml,
# which is far off for flour (about 0.53 g per ml). Each row is (name pattern, words that rule it out, typical grams per US cup).
# The values are rounded typical figures for a cup spooned and leveled, as in USDA FoodData Central household measures and the
# King Arthur and Cook's Illustrated ingredient weight charts; real products vary a little. A food's own serving_ml (or serving_g)
# always wins, and a conversion that uses a row is still marked estimated. Order matters: the first match wins, so specific
# names come before general ones. Names are matched in lower case with apostrophes removed.
GRAMS_PER_CUP = [
    (r"\bbread flour\b", None, 127),
    (r"whole[- ]?wheat flour|wholemeal flour|flour, whole|wheat flour, whole", None, 120),
    (r"\bcake flour\b", None, 114),
    (r"almond (flour|meal)", None, 96),
    (r"\bcoconut flour\b", None, 112),
    (r"\brye flour\b", None, 102),
    (r"\ball[- ]?purpose\b|\bplain flour\b|\bwhite flour\b|^flour\b|wheat flour, white|\bunbleached flour\b", r"\b(rice|corn|oat|buckwheat|tapioca|potato|chickpea|soy|coconut|almond)\b", 125),
    (r"brown sugar", None, 213),  # packed
    (r"powdered sugar|confectioners sugar|confectioner s sugar|icing sugar", None, 120),
    (r"\bsugar\b", r"\b(free|snap|cookie|cookies|cereal|substitute|maple|beet|cane syrup|cinnamon|coated|frosted)\b", 200),  # granulated
    (r"peanut butter", None, 258),
    (r"\bbutter\b", r"\b(peanut|almond|cashew|nut|seed|cookie|cookies|cracker|crackers|cocoa|shea|popcorn|bean|beans|chicken|cake|cream|spread|flavored)\b", 227),
    (r"\bhoney\b", r"\b(mustard|roasted|nut|nuts|bun|bunches|bbq|barbecue|cereal|granola|bar)\b", 340),
    (r"maple syrup", None, 322),
    (r"\b(butter)?milk\b", r"\b(chocolate|powder|powdered|dry|condensed|evaporated|coconut|almond|soy|oat|rice|cashew|cookie|cookies|shake|malted|bar)\b", 245),
    (r"heavy cream|whipping cream|heavy whipping", None, 238),
    (r"sour cream", None, 230),
    (r"\b(plain |greek )?yogh?urt\b", r"\b(frozen|bar|covered|coated|chips?|pretzel|raisins?|granola|drink|smoothie|dip)\b", 245),
    (r"^(drinking |tap |filtered |cold |warm )?water\b", None, 237),
    (r"\b(vegetable|canola|olive|sunflower|corn|peanut|avocado|safflower|soybean|coconut|sesame)? ?oil\b",
     r"\b(tuna|sardines?|anchov\w*|fish|packed|spray|dressing|vinaigrette|chips?|popcorn|salmon)\b|\bin oil\b", 218),
    (r"quick (cooking )?oats", None, 80),
    (r"\brolled oats\b|old[- ]fashioned (rolled )?oats|\boats\b|\boatmeal\b", r"\b(flour|bran|milk|cereal|bar|bars|cookie|cookies|packet|instant)\b", 90),
    (r"\brice\b", r"\b(cooked|steamed|fried|flour|milk|cereal|cake|cakes|pudding|vinegar|noodles?|crisp|crispy|krispies|paper|wine|syrup|bran|pilaf|mix|bowl|and|with|pasta)\b", 185),  # uncooked
    (r"cocoa powder|unsweetened cocoa|\bcocoa\b", r"\b(butter|mix|hot|drink|beverage|krispies|puffs|cereal|chocolate)\b", 85),
    (r"chocolate (chips|morsels)", None, 170),
    (r"\bsalt\b", r"\b(pepper|vinegar|pretzels?|crackers?|caramel|chips?|peanuts?|nuts?|seasoning|garlic|free|substitute|lite|light|and)\b", 288),  # table salt
    (r"baking powder", None, 192),
    (r"baking soda|sodium bicarbonate", None, 288),
    (r"corn ?starch", None, 128),
    (r"corn ?meal", None, 157),
    (r"\braisins?\b", r"\b(bran|cereal|cookie|cookies|bread|oatmeal|bagel|bagels)\b", 145),
    (r"grated parmesan|parmesan, grated|parmesan cheese, grated", None, 100),
]
_DENSITY = [(re.compile(inc), re.compile(exc) if exc else None, cup / VOLUME["cup"]) for inc, exc, cup in GRAMS_PER_CUP]


def density(food):
    """Typical grams per ml for a food matched by name keywords (GRAMS_PER_CUP), or None when no keyword matches."""
    name = re.sub(r"['\u2019]", "", str(food.get("name") or "").lower())
    name = re.sub(r"\s+", " ", name).strip()
    for inc, exc, per_ml in _DENSITY:
        if inc.search(name) and not (exc and exc.search(name)):
            return per_ml
    return None


def _profile(food):
    """Return (label unit, label amount, grams, grams estimated, ml, ml estimated) per serving."""
    unit = parse_unit(food.get("serving_unit"))
    amount = _pos(food.get("serving_amount"))
    if amount is None:
        raise ValueError("Food has no valid serving_amount")
    sg, sml = _pos(food.get("serving_g")), _pos(food.get("serving_ml"))
    # The label's own grams and ml always win. Only the missing family is estimated: with the typical density of the food when its
    # name matches a keyword (density), else 1 g per ml.
    d = density(food) if not (sg and sml) else None
    to_ml = (lambda grams: grams / d) if d else (lambda grams: grams)
    to_g = (lambda millilitres: millilitres * d) if d else (lambda millilitres: millilitres)
    g = ge = ml = mle = None
    if unit in MASS:
        g, ge = amount * MASS[unit], False
        ml, mle = (sml, False) if sml else (to_ml(g), True)
    elif unit in VOLUME:
        ml, mle = amount * VOLUME[unit], False
        g, ge = (sg, False) if sg else (to_g(ml), True)
    else:
        g, ml = sg, sml
        ge = mle = False
        if g and not ml:
            ml, mle = to_ml(g), True
        elif ml and not g:
            g, ge = to_g(ml), True
    return unit, amount, g, bool(ge), ml, bool(mle)


def _is_measure(label_unit):
    """True when the label unit is not a count word (a weight, a volume, serving or percent)."""
    return label_unit in MASS or label_unit in VOLUME or label_unit in PSEUDO


def _convert(food, amount, unit):
    """Return (servings, estimated). Raises ValueError for bad amounts or unreachable units."""
    amount = _pos(amount)
    if amount is None:
        raise ValueError("Amount must be greater than zero")
    unit = unit_or_blank(unit)
    label_unit, label_amount, g, ge, ml, mle = _profile(food)
    if unit == label_unit or same_word(unit, label_unit):
        return amount / label_amount, False
    if unit in (COUNT, BLANK) or is_custom(unit):  # a plain count: the label's own count word when it has one, else label servings
        return (amount, False) if _is_measure(label_unit) else (amount / label_amount, False)
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
    if label_unit != COUNT:
        out.append(entry(COUNT, 1.0, False))
    return out


def default_pick(food):
    """(amount, unit) a picker starts from for a food nobody has logged yet: the package's own serving, for example 30 g, 1 cup or
    2 slice. When the label unit is only "serving" (or %) there is nothing better to show unless the label gives a weight or a
    volume, then that is used (1 serving of 30 g starts at 30 g). "serving" stays available as a unit either way."""
    label_unit, label_amount, _, _, _, _ = _profile(food)
    if label_unit in PSEUDO:
        for key, unit in (("serving_g", "g"), ("serving_ml", "ml")):
            v = _pos(food.get(key))
            if v:
                return v, unit
    return label_amount, label_unit


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


def grams(food, amount, unit):
    """Grams in amount of unit, rounded to 0.1, or None when the food's weight is unknown or only estimated,
    or when the amount is already in grams."""
    try:
        u = unit_or_blank(unit)
        servings, estimated = _convert(food, amount, u)
        g, ge = _profile(food)[2:4]
    except ValueError:
        return None
    if is_custom(u) and not same_word(u, _profile(food)[0]):  # a typed unit is only counted like Count, so its weight is not known
        return None
    if u == "g" or not g or ge or estimated:
        return None
    return round(servings * g, 1)


# Line units that only say "this many of the thing", for counts without a unit such as "2 eggs".
PLAIN_COUNTS = (COUNT, "piece", "each", "whole", "unit", "item", "large", "medium", "small")


def match_amount(food, amount, unit):
    """Amount and unit for a recipe line ("1 cup", "2 tbsp", "2" eggs) matched to food, without asking the user.

    Returns {"amount", "unit", "check"} (plus "estimated": True when only the 1 g per ml guess reaches the unit) or None when
    the line has no amount (salt to taste). A blank unit or Count is a plain count (see PLAIN_COUNTS).
    - The line's own unit when the food reaches it at all, as the picker offers it: same unit, weight to weight, volume to
      volume, and weight to volume through the food's own density (serving_g and serving_ml) or label count word. A unit
      reachable only through the 1 g per ml guess is used too, with "estimated": True (the same math the picker uses).
    - A plain count (no unit, count, piece, each) uses the label's count word when it has one, else label servings.
    - A typed unit the server does not know (can, clove, pinch) keeps its word, counts like Count (no conversion) and never
      asks for a check, unless it is the label's own count word.
    - A known measure that cannot be reached (a cup of a food with no volume, no weight) is unreachable:
      one label serving with check True, so the user confirms the amount."""
    a = _pos(amount)
    if a is None:
        return None
    label_unit, label_amount = _profile(food)[:2]
    try:
        u = unit_or_blank(unit) or None
    except ValueError:
        u = None
    if u is not None and is_custom(u) and parse_unit(u) not in PLAIN_COUNTS:
        if same_word(u, label_unit):
            return {"amount": a, "unit": label_unit, "check": False}
        return {"amount": a, "unit": u, "check": False}
    if u is not None and u not in PLAIN_COUNTS:
        for entry in available_units(food):
            if entry["unit"] == u:
                return {"amount": a, "unit": u, "check": False, **({"estimated": True} if entry["estimated"] else {})}
    elif not _is_measure(label_unit):
        return {"amount": a, "unit": label_unit, "check": False}
    else:
        return {"amount": a, "unit": SERVING, "check": False}
    return {"amount": label_amount, "unit": label_unit, "check": True}
