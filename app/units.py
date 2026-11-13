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
# Count is a plain "this many of the thing" unit and BLANK is no unit at all (stored as ""). Both mean one of the label's count word
# (2 slice per serving on a "2 slice" label). On a label that is a measure (100 g, 1 cup, 1 serving) a count has no known weight,
# so a recipe line never converts it (match_amount asks for a check) and the picker does not offer it.
# Package units (can, jar, stick) and fuzzy units (clove, slice, pinch) are structured units too: kept on the line, shown with a
# plural ("2 cloves"), converted only through a printed size ("1 (15 oz) can") or the label's own word ("1 clove (3 g)").
# A custom unit is any other typed word (to taste, shell): kept as typed (MAX_UNIT characters, no control characters) and treated
# like Count, never converted.
COUNT, BLANK = "count", ""
MAX_UNIT = 30
PACKAGE_UNITS = ("can", "jar", "bottle", "bag", "box", "packet", "package", "carton", "stick")
FUZZY_UNITS = ("clove", "slice", "bunch", "head", "sprig", "pinch", "dash", "handful", "piece", "fillet", "rib", "stalk")
COUNTISH = (*PACKAGE_UNITS, *FUZZY_UNITS)
LABELS = {"floz": "fl oz", SERVING: "serving", PCT: "% of serving", COUNT: "count"}
PSEUDO_DEFAULT = {SERVING: 1.0, PCT: 100.0}
# Display order for the non-label units offered in the picker.
ORDER = ["g", "oz", "lb", "kg", "ml", "floz", "cup", "tbsp", "tsp", "l"]
KNOWN = {*MASS, *VOLUME, *PSEUDO, COUNT, *COUNTISH}
# Line units that only say "this many of the thing", for counts without a unit such as "2 eggs".
PLAIN_COUNTS = (COUNT, "piece", "each", "whole", "unit", "item", "large", "medium", "small")
# Why match_amount asks for a check: a count or fuzzy unit with no known weight on the food (2 cloves of a 100 g label), a package
# unit with no printed size (1 can), a measure the food cannot reach (a cup of a food with no volume and no weight). no_amount is
# core's for a line with no amount. The client words each one (util.js checkReasonText).
NO_WEIGHT, NO_SIZE, NO_CONVERT, NO_AMOUNT = "no_weight", "no_size", "no_convert", "no_amount"

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
    "pkg": "package", "pkgs": "package", "pk": "package", "pack": "package", "pkt": "packet", "pc": "piece", "pcs": "piece",
    "filet": "fillet", "tin": "can",
    **{u: u for u in COUNTISH},
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
    """True for a typed unit that is neither blank, count, a package or fuzzy unit nor a measure the server knows (to taste, shell)."""
    return bool(unit) and unit not in KNOWN


def unit_or_blank(text):
    """The unit to store: no unit at all ("", None, "-", "none") is BLANK (""), a known unit or alias is its canonical name
    ("Cups" -> cup, "Count" -> count) and anything else is a custom unit kept as typed (trimmed, "Pinch" stays "Pinch")."""
    t = clean_unit_text(text)
    if t.lower() in ("", "-", "none"):
        return BLANK
    p = parse_unit(t)
    return p if p in KNOWN else t


TASTE = re.compile(r"\b(to taste|as needed)\b", re.I)
_VULGAR = {"\u00bd": (1, 2), "\u00bc": (1, 4), "\u00be": (3, 4), "\u2153": (1, 3), "\u2154": (2, 3), "\u2155": (1, 5), "\u2156": (2, 5),
           "\u2157": (3, 5), "\u2158": (4, 5), "\u2159": (1, 6), "\u215a": (5, 6), "\u215b": (1, 8), "\u215c": (3, 8),
           "\u215d": (5, 8), "\u215e": (7, 8)}
_VULGAR_RE = re.compile("(\\d+)?\\s*([" + "".join(_VULGAR) + "])")


def normalize_fractions(text):
    """Unicode fractions as plain ones: "1 \u00bd" and "1\u00bd" are "1 1/2", "\u00be" is "3/4"."""
    def one(m):
        n, d = _VULGAR[m.group(2)]
        return f"{m.group(1)} {n}/{d}" if m.group(1) else f"{n}/{d}"
    return _VULGAR_RE.sub(one, str(text or ""))


_LEAD_NUM = r"\d+\s+\d+/\d+|\d+-\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?"
_LEAD = re.compile(rf"^\s*(?P<a>{_LEAD_NUM})(?:\s*(?:-|\u2013|to)\s*(?P<b>{_LEAD_NUM}))?(?![\d/])\s*(?P<rest>.*)$", re.I | re.S)


def _lead_number(text):
    t = str(text).replace(",", ".").replace("-", " ", 1) if re.match(r"\d+-\d+/\d+$", str(text)) else str(text).replace(",", ".")
    total = 0.0
    try:
        for part in t.split():
            if "/" in part:
                n, d = part.split("/")
                total += float(n) / float(d)
            else:
                total += float(part)
    except (ValueError, ZeroDivisionError):
        return None
    return _pos(total)


def lead_amount(text):
    """(amount, rest) for a line that starts with a real amount ("1 \u00bd tablespoons olive oil", "1-1/2 cups", "2-3 cloves" is 2.5), else None."""
    m = _LEAD.match(normalize_fractions(text))
    if not m:
        return None
    a = _lead_number(m.group("a"))
    b = _lead_number(m.group("b")) if m.group("b") else None
    if a is None:
        return None
    return (a + b) / 2 if b is not None and b > a else a, m.group("rest").strip()


def lead_unit(rest):
    """The known unit that opens the rest of a line after its amount ("tablespoons olive oil" is tbsp), else None."""
    r = str(rest or "").strip()
    m = re.match(r"(fl\.?\s*oz\.?|fluid\s+ounces?)\b", r, re.I)
    if m:
        return "floz"
    m = re.match(r"([A-Za-z]+)\.?(?=\s|$|,)", r)
    return known_unit(m.group(1)) if m else None


def strip_taste(name, note):
    """(name, note) with a to taste or as needed phrase moved from the name into the note. Used on a line that has an amount, which keeps it."""
    name = str(name or "").strip()
    m = TASTE.search(name)
    if not m:
        return name, note
    clean = re.sub(r"\s+", " ", TASTE.sub("", name)).strip(" ,;-") or name
    phrase = m.group(1).lower()
    note = str(note or "").strip()
    return clean, (note if TASTE.search(note) else (f"{phrase}, {note}" if note else phrase))


def taste_line(text, note, unit, name, amount=None):
    """For a line that says to taste or as needed (salt to taste, pepper as needed): (name, note) with the phrase moved into the note and
    the name without it, else None. Such a line has no amount and no unit and is never a count. A line with a real amount (amount above
    0, or text that starts with one, "1 \u00bd tbsp olive oil (more as needed)") is never a taste line: the phrase stays a note."""
    if _pos(amount) is not None or lead_amount(text):
        return None
    found = next((m for m in (TASTE.search(str(x or "")) for x in (note, unit, name, text)) if m), None)
    if not found:
        return None
    phrase = found.group(1).lower()
    clean = re.sub(r"\s+", " ", TASTE.sub("", str(name or ""))).strip(" ,;-") or str(name or "").strip()
    note = str(note or "").strip()
    return clean, note if TASTE.search(note) else (f"{phrase}, {note}" if note else phrase)


def known_unit(text):
    """The canonical known unit for text ("Cups" -> cup, "tablespoons" -> tbsp, "Cloves" -> clove, "Count" -> count), else None
    for blank, none and any word the table does not know (shell, to taste)."""
    try:
        u = unit_or_blank(text)
    except ValueError:
        return None
    return u if u in KNOWN else None


def unit_word(unit, amount):
    """A unit as a word after an amount: package and fuzzy units take a simple plural above 1 (2 cloves, 3 pinches, 2 boxes),
    fl oz is spelled out, every other unit as it is."""
    u = str(unit or "")
    if u == "floz":
        return "fl oz"
    if u in COUNTISH and _pos(amount) is not None and float(amount) > 1:
        return u + ("es" if re.search(r"(s|sh|ch|x|z)$", u) else "s")
    return u


def is_countlike(unit):
    """True for a unit that only counts things: blank, count, a plain count word (piece, large), a package or fuzzy unit, or a typed word."""
    u = unit_or_blank(unit) if unit not in (None, BLANK) else BLANK
    return u in (BLANK, COUNT) or u in COUNTISH or u in PLAIN_COUNTS or is_custom(u)


def line_unit(amount, unit, name=""):
    """(unit, name) for a recipe line that comes from Claude, a web page or Search, never a custom unit.
    No amount: no unit (None), the line stays plain text ("salt to taste"). An amount with a known unit or alias: the canonical unit,
    package and fuzzy units included (2 cloves garlic stays clove and garlic). An amount with no unit or a word the table does not
    know: count, the name as it is."""
    name = str(name or "").strip()
    if _pos(amount) is None:
        return None, name
    return known_unit(unit) or COUNT, name


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
    # Issue #45 step 5: chopped vegetables, cheese, nuts, beans, liquids and ground spices. Grams per US cup as in USDA FoodData
    # Central household measures (a ground spice row is its grams per tsp x 48).
    (r"shredded (cheddar|cheese)|cheddar, shredded|cheese, shredded", None, 113),
    (r"(shredded|grated) mozzarella|mozzarella, shredded", None, 112),
    (r"cream cheese", None, 232),
    (r"cottage cheese", None, 226),
    (r"\bricotta\b", None, 246),
    (r"green onions?|spring onions?|scallions?", None, 100),
    (r"\bonions?\b", r"\b(powder|rings?|soup|dip|flakes|salt|dried|dehydrated|fried)\b", 160),  # chopped
    (r"\b(bell|sweet|green|red|yellow|orange) peppers?\b|peppers?, (sweet|bell)", r"\b(flakes|crushed|ground|powder|sauce|jelly|chili|black|white)\b", 150),  # chopped
    (r"\bcarrots?\b", r"\b(juice|cake|soup|baby food)\b", 128),  # chopped
    (r"\bcelery\b", r"\b(salt|seed|seeds|soup)\b", 101),  # chopped
    (r"\bbroccoli\b", r"\b(soup|casserole)\b", 91),
    (r"\bcauliflower\b", r"\b(rice|crust|soup)\b", 107),
    (r"\bcabbage\b", r"\b(rolls?|soup)\b", 89),
    (r"\bmushrooms?\b", r"\b(soup|sauce|dried|powder)\b", 70),
    (r"\bzucchini\b", r"\b(bread|noodles)\b", 124),
    (r"\bspinach\b", r"\b(cooked|boiled|frozen|dip|pasta|tortilla|wrap|artichoke)\b", 30),  # raw
    (r"\bspinach\b", r"\b(dip|pasta|tortilla|wrap|artichoke)\b", 180),  # cooked
    (r"\bkale\b", r"\b(chips?)\b", 67),
    (r"\bpeas\b", r"\b(chick|split|black[- ]eyed|soup|snap|snow|protein)\b", 134),  # frozen green peas
    (r"\bcorn\b", r"\b(starch|meal|flour|syrup|chips?|flakes|oil|bread|dog|tortillas?|cereal|pops?|nuts?|popcorn|chowder)\b", 154),
    (r"\b(diced|crushed|stewed) tomato|tomatoes, (canned|crushed|diced|stewed)", None, 240),
    (r"tomato paste", None, 262),
    (r"tomato sauce|marinara|pasta sauce", None, 245),
    (r"\btomato(es)?\b", r"\b(paste|sauce|soup|juice|ketchup|sun[- ]dried|dried|powder)\b", 180),  # chopped fresh
    (r"\bpotato(es)?\b", r"\b(sweet|chips?|fries|flakes|salad|starch|flour|mashed|tots?|soup|skins?)\b", 150),  # diced
    (r"sweet potato", r"\b(fries|chips?|pie)\b", 133),
    (r"chick ?peas?|garbanzo", r"\b(flour|pasta|snacks?)\b", 164),  # cooked or canned, drained
    (r"\blentils?\b", r"\b(cooked|boiled|soup|pasta|chips?)\b", 192),  # dry
    (r"\blentils?\b", r"\b(soup|pasta|chips?)\b", 198),  # cooked
    (r"\bbeans?\b", r"\b(green|string|snap|coffee|jelly|vanilla|cocoa|sprouts?|baked|refried|soup|chips?|pasta|flour)\b", 172),  # cooked or canned, drained
    (r"\balmonds?\b", r"\b(milk|butter|flour|meal|extract|bar|bars)\b", 143),
    (r"\bwalnuts?\b", None, 117),  # chopped
    (r"\bpecans?\b", r"\b(pie)\b", 109),  # chopped
    (r"\bcashews?\b", r"\b(milk|butter)\b", 137),
    (r"\bpeanuts?\b", r"\b(butter|oil|sauce|flour|brittle)\b", 146),
    (r"\b(chicken|beef|vegetable|bone) (broth|stock)\b|\bbroth\b|\bstock\b", None, 240),
    (r"soy sauce|tamari", None, 255),
    (r"\bvinegar\b", None, 239),
    (r"\bketchup\b", None, 272),
    (r"\bmayonnaise\b|\bmayo\b", None, 220),
    (r"coconut milk", r"\b(beverage|drink)\b", 226),  # canned
    (r"vanilla extract", None, 208),
    (r"\bblueberries\b", r"\b(muffins?|dried|pie)\b", 148),
    (r"\bstrawberries\b", r"\b(jam|dried|preserves)\b", 166),  # sliced
    (r"\braspberries\b", r"\b(jam|preserves)\b", 123),
    (r"(white|brown|jasmine|basmati)? ?rice, cooked|cooked (white |brown )?rice", None, 158),
    (r"\bquinoa\b", r"\b(cooked|flour|pasta)\b", 170),  # uncooked
    (r"bread ?crumbs|panko", None, 108),
    (r"ground cinnamon|cinnamon, ground|^cinnamon\b|spices?, cinnamon", None, 125),  # 2.6 g per tsp
    (r"\bcumin\b", None, 101),  # 2.1 g per tsp
    (r"\bpaprika\b", None, 110),  # 2.3 g per tsp
    (r"chil[ei] powder", None, 130),  # 2.7 g per tsp
    (r"black pepper|pepper, black|ground pepper", None, 110),  # 2.3 g per tsp
    (r"garlic powder", None, 149),  # 3.1 g per tsp
    (r"onion powder", None, 115),  # 2.4 g per tsp
    (r"\boregano\b", None, 48),  # dried, 1 g per tsp
    (r"ground ginger|ginger, ground", None, 86),  # 1.8 g per tsp
    (r"\bturmeric\b", None, 144),  # 3 g per tsp
    (r"\bnutmeg\b", None, 106),  # 2.2 g per tsp
    (r"\bgarlic\b", r"\b(powder|salt|bread|oil|sauce|press)\b", 136),  # minced, 2.8 g per tsp
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


# ---------- unit weights: what one clove, can or large weighs (issue #45 steps 4 and 5) ----------
# A food_units row says one unit of a food weighs this many grams. Sources in order of trust, best first: user (the viewer's own
# weight), fdc and off (the source's own data, exact, global), table (the typical weights below, estimated), ai (Claude's
# estimate, per user, estimated). A printed size on the recipe line ("1 (15 oz) can") sits between user and fdc. core attaches the
# rows a viewer may see as food["food_units"]; the table rows are worked out here from the food's name, so they need no database.
WEIGHT_SOURCES = ("user", "fdc", "off", "table", "ai")
SIZE_WORDS = ("small", "medium", "large")
VOLUME_ROW_UNITS = ("cup", "tbsp", "tsp", "floz")  # a volume row gives the food's own density (1 cup chopped is 160 g)
WEIGHT_UNITS = (*COUNTISH, COUNT, *SIZE_WORDS, *VOLUME_ROW_UNITS)
MAX_UNIT_GRAMS = 100000.0

# Typical piece weights, (name pattern, words that rule it out, unit, grams). Rounded values from USDA FoodData Central household
# measures (SR Legacy portions) and common recipe conventions; real pieces vary, so every row is an estimate (source table).
# count is one of the thing when the line gives no size (2 eggs means large eggs, 1 onion a medium one).
_EGG = (r"\beggs?\b", r"\b(white|whites|yolks?|noodles?|plant|substitute|nog|rolls?|salad|beaters|replacer)\b")
_ONION = (r"\bonions?\b", r"\b(green|spring|powder|rings?|soup|dip|flakes|salt|dried|fried)\b")
_POTATO = (r"\bpotato(es)?\b", r"\b(sweet|chips?|fries|flakes|salad|starch|flour|mashed|tots?|soup|skins?)\b")
_CARROT = (r"\bcarrots?\b", r"\b(juice|cake|soup|baby)\b")
_TOMATO = (r"\btomato(es)?\b", r"\b(paste|sauce|soup|juice|ketchup|sun[- ]dried|dried|canned|diced|crushed|stewed|cherry|grape|salsa)\b")
_PEPPER = (r"\b(bell|sweet|green|red|yellow|orange) peppers?\b|peppers?, (sweet|bell)", r"\b(flakes|crushed|ground|powder|sauce|jelly|chili|black|white)\b")
_BANANA = (r"\bbananas?\b", r"\b(chips?|bread|pudding|muffins?|dried|peppers?)\b")
_APPLE = (r"\bapples?\b", r"\b(juice|sauce|cider|vinegar|pie|chips?|butter|crisp|dried|pineapple|custard)\b")
_HERBS = r"\b(thyme|rosemary|parsley|cilantro|coriander leaves|dill|mint|basil|oregano|sage|tarragon|marjoram)\b"
_DRIED = r"\b(dried|ground|flakes)\b"
_SEASONING = r"\b(salt|pepper|cinnamon|cumin|paprika|cayenne|nutmeg|cloves, ground|ground|spices?|seasoning|chili powder|garlic powder|onion powder|oregano|thyme|baking soda|baking powder|sugar|allspice|ginger|turmeric|saffron|herbs?)\b"
PIECE_GRAMS = [
    (r"garlic", r"\b(powder|salt|bread|oil|sauce|minced in|press)\b", "clove", 3),
    (r"garlic", r"\b(powder|salt|bread|oil|sauce|press)\b", "head", 40),
    (r"egg whites?|eggs?, white", None, COUNT, 33),
    (r"egg yolks?|eggs?, yolk", None, COUNT, 17),
    (*_EGG, COUNT, 50), (*_EGG, "large", 50), (*_EGG, "medium", 44), (*_EGG, "small", 38),
    (*_ONION, COUNT, 110), (*_ONION, "medium", 110), (*_ONION, "small", 70), (*_ONION, "large", 150),
    (r"green onions?|spring onions?|scallions?", None, COUNT, 15),
    (r"green onions?|spring onions?|scallions?", None, "bunch", 100),
    (r"\bbutter\b", r"\b(peanut|almond|cashew|nut|seed|cookie|cookies|cocoa|shea|apple|bean|beans|cream)\b", "stick", 113),
    (r"\bcelery\b", r"\b(salt|seed|seeds|soup|root)\b", "rib", 40),
    (r"\bcelery\b", r"\b(salt|seed|seeds|soup|root)\b", "stalk", 40),
    (_HERBS, _DRIED, "sprig", 1),
    (r"cilantro|coriander leaves", _DRIED, "bunch", 60),
    (r"\bparsley\b", _DRIED, "bunch", 60),
    (r"\bkale\b", r"\b(chips?)\b", "bunch", 200),
    (r"\bspinach\b", r"\b(frozen|dip|pasta)\b", "bunch", 340),
    (r"\bbread\b", r"\b(crumbs|stuffing|pudding|flour|fruit|sticks?|mix|machine)\b", "slice", 28),
    (r"\bcheese\b", r"\b(cream|cottage|ricotta|sauce|spread|dip|shredded|grated|cake|puffs?)\b", "slice", 21),
    (_SEASONING, None, "pinch", 0.36),
    (_SEASONING, None, "dash", 0.6),
    (r"\b(nuts?|almonds?|walnuts?|pecans?|cashews?|peanuts?|pistachios?|hazelnuts?|chips?|berries|blueberries|raisins?)\b", r"\b(butter|milk|flour|oil)\b", "handful", 30),
    (r"\b(spinach|arugula|lettuce|greens|kale|basil)\b", None, "handful", 25),
    (r"\blettuce\b|\biceberg\b", r"\b(romaine)\b", "head", 539),
    (r"\bromaine\b", None, "head", 626),
    (r"\bcabbage\b", r"\b(rolls?|soup)\b", "head", 908),
    (r"\bcauliflower\b", r"\b(rice|crust|soup)\b", "head", 588),
    (r"\bbroccoli\b", r"\b(soup|casserole)\b", "head", 608),
    (r"\bbroccoli\b", r"\b(soup|casserole)\b", "bunch", 608),
    (*_POTATO, COUNT, 170), (*_POTATO, "medium", 170), (*_POTATO, "small", 92), (*_POTATO, "large", 300),
    (r"sweet potato", r"\b(fries|chips?|pie)\b", COUNT, 130), (r"sweet potato", r"\b(fries|chips?|pie)\b", "medium", 130),
    (*_CARROT, COUNT, 61), (*_CARROT, "medium", 61), (*_CARROT, "small", 50), (*_CARROT, "large", 72),
    (r"\blemons?\b", r"\b(juice|zest|peel|pepper|curd|grass|ade|extract)\b", COUNT, 58),
    (r"\blimes?\b", r"\b(juice|zest|peel|ade|leaves)\b", COUNT, 67),
    (r"cherry tomato|grape tomato", None, COUNT, 17),
    (*_TOMATO, COUNT, 123), (*_TOMATO, "medium", 123), (*_TOMATO, "small", 91), (*_TOMATO, "large", 182),
    (*_PEPPER, COUNT, 120), (*_PEPPER, "medium", 120), (*_PEPPER, "small", 74), (*_PEPPER, "large", 164),
    (r"jalape[nñ]o", None, COUNT, 14),
    (*_BANANA, COUNT, 118), (*_BANANA, "medium", 118), (*_BANANA, "small", 101), (*_BANANA, "large", 136),
    (*_APPLE, COUNT, 182), (*_APPLE, "medium", 182), (*_APPLE, "small", 149), (*_APPLE, "large", 223),
    (r"\boranges?\b", r"\b(juice|zest|peel|chicken|marmalade|soda)\b", COUNT, 131),
    (r"\bavocados?\b", r"\b(oil|toast)\b", COUNT, 150),
    (r"\bzucchini\b", r"\b(bread|noodles)\b", COUNT, 196),
    (r"\bmushrooms?\b", r"\b(soup|sauce|dried|powder)\b", COUNT, 18),
    (r"\bstrawberr(y|ies)\b", r"\b(jam|dried|preserves)\b", COUNT, 12),
    (r"bay lea(f|ves)", None, COUNT, 0.2),
    (r"chicken breast|chicken, breast|breast, chicken", r"\b(nuggets?|patty|patties|sandwich)\b", COUNT, 174),
    (r"chicken breast|chicken, breast|breast, chicken", r"\b(nuggets?|patty|patties|sandwich)\b", "fillet", 174),
    (r"\bsalmon\b", r"\b(canned|smoked|jerky)\b", "fillet", 170),
    (r"\b(tilapia|cod|white fish)\b", None, "fillet", 113),
]
# Standard package sizes when the recipe prints none, (name pattern, words that rule it out, package units, net grams). Common US
# sizes: a 15 oz can of beans, a 14.5 oz can of tomatoes, an 8 oz brick of cream cheese, a 1 lb box of pasta.
PACKAGE_GRAMS = [
    (r"tomato paste", None, ("can",), 170),
    (r"(diced|crushed|stewed|whole peeled) tomato|tomatoes, (canned|crushed|diced|stewed)|canned tomato", None, ("can",), 411),
    (r"tomato sauce", None, ("can",), 425),
    (r"chick ?peas?|garbanzo", r"\b(flour|pasta|snacks?)\b", ("can",), 425),
    (r"\bbeans?\b", r"\b(green|string|snap|coffee|jelly|vanilla|cocoa|sprouts?|soup|chips?|pasta|flour)\b", ("can",), 425),
    (r"green beans", None, ("can",), 411),
    (r"cream of \w+|condensed|\bsoup\b", r"\b(mix|dry|bowl)\b", ("can",), 298),
    (r"coconut milk", r"\b(beverage|drink)\b", ("can",), 400),
    (r"\btuna\b", None, ("can",), 142),
    (r"\bcorn\b", r"\b(starch|meal|flour|syrup|chips?|flakes|oil|bread|tortillas?|cereal|frozen)\b", ("can",), 432),
    (r"cream cheese", None, ("package", "box"), 227),
    (r"\bfrozen\b.*\b(vegetables?|peas|corn|broccoli|spinach|green beans|carrots|mixed)\b|\b(vegetables?|peas|corn|broccoli|spinach|green beans|mixed), frozen", None, ("bag", "package"), 340),
    (r"\b(pasta|spaghetti|penne|macaroni|rigatoni|fettuccine|linguine|rotini|fusilli|farfalle|ziti|orzo|lasagna)\b", r"\b(sauce|salad|cooked|soup)\b", ("box", "package", "bag"), 454),
    (r"\b(chicken|beef|vegetable|bone) (broth|stock)\b|\bbroth\b|\bstock\b", None, ("carton", "box"), 946),
]
_PIECES = [(re.compile(inc), re.compile(exc) if exc else None, unit, float(g)) for inc, exc, unit, g in PIECE_GRAMS]
_PACKAGES = [(re.compile(inc), re.compile(exc) if exc else None, units_, float(g)) for inc, exc, units_, g in PACKAGE_GRAMS]
_SIZE_HINT = re.compile(r"\b(extra[- ]large|jumbo|large|medium|small)\b", re.I)


def _food_name(food):
    name = re.sub(r"['’]", "", str(food.get("name") or "").lower())
    return re.sub(r"\s+", " ", name).strip()


def package_note(unit):
    """The reason text of a standard package size: "Standard can size assumed"."""
    return f"Standard {unit} size assumed"


def table_weights(food):
    """The typical weights (PIECE_GRAMS) and standard package sizes (PACKAGE_GRAMS) that match the food's name, as food_units
    rows with source table and estimated True. The first matching row wins for each unit."""
    name = _food_name(food)
    out = {}
    for inc, exc, unit, g in _PIECES:
        if unit not in out and inc.search(name) and not (exc and exc.search(name)):
            out[unit] = {"unit": unit, "grams": g, "source": "table", "estimated": True}
    for inc, exc, pkgs, g in _PACKAGES:
        if inc.search(name) and not (exc and exc.search(name)):
            for unit in pkgs:
                out.setdefault(unit, {"unit": unit, "grams": g, "source": "table", "estimated": True, "note": package_note(unit)})
    return list(out.values())


def weight_unit(text):
    """The canonical unit of a food_units row (clove, can, count, large, cup), or None for a unit a row cannot hold (g, serving)."""
    try:
        u = unit_or_blank(text)
    except ValueError:
        return None
    u = parse_unit(u) if u else u
    if u in ("each", "whole", "item", "unit"):
        u = COUNT
    return u if u in WEIGHT_UNITS else None


def unit_weights(food):
    """{unit: row} with the most trusted row for each unit (WEIGHT_SOURCES order): the rows core attached (food["food_units"]) and
    the table rows. Each row is {"unit", "grams" (one unit), "source", "estimated", "note"?}."""
    best, rank = {}, {}
    for r in [*(food.get("food_units") or []), *table_weights(food)]:
        u, g, src = r.get("unit"), _pos(r.get("grams")), r.get("source")
        if u not in WEIGHT_UNITS or g is None or src not in WEIGHT_SOURCES:
            continue
        k = WEIGHT_SOURCES.index(src)
        if u not in best or k < rank[u]:
            best[u] = {"unit": u, "grams": g, "source": src, "estimated": bool(r.get("estimated")) or src in ("table", "ai"),
                       **({"note": r["note"]} if r.get("note") else {})}
            rank[u] = k
    return best


def _volume_row(food):
    """The most trusted volume row of the food (one cup chopped is 160 g), cup first, else None."""
    w = unit_weights(food) if food.get("food_units") else {}
    rows = [w[u] for u in VOLUME_ROW_UNITS if u in w]
    return min(rows, key=lambda r: WEIGHT_SOURCES.index(r["source"])) if rows else None


def size_hint(text):
    """small, medium or large named in a recipe line's name ("large eggs"), else None. Extra large and jumbo count as large."""
    m = _SIZE_HINT.search(str(text or ""))
    if not m:
        return None
    w = m.group(1).lower()
    return w if w in SIZE_WORDS else "large"


def _is_plain(unit):
    return unit in (BLANK, COUNT, None) or unit in PLAIN_COUNTS


def count_row(food, unit, hint=None):
    """The food_units row that gives a count-like unit its weight on this food, or None. The label's own word (and, on a count
    word label, a plain count) never needs one. A size word (large) uses its own row, else count. A plain count (blank, count,
    each) uses the size the line names (hint, "large eggs"), else count, medium, large, small. A package or fuzzy unit uses
    its own row. None when the label has no weight at all (nothing to convert through)."""
    try:
        u = unit_or_blank(unit) if unit not in (None, BLANK) else BLANK
        label_unit, _, g = _profile(food)[:3]
    except ValueError:
        return None
    if not g or not is_countlike(u) or (u and same_word(u, label_unit)):
        return None
    p = parse_unit(u) if u else u
    if p in ("each", "whole", "item", "unit"):
        p = COUNT
    if _is_plain(p) and p not in COUNTISH and not _is_measure(label_unit):
        return None  # a count word label: the label's own word is exact
    w = unit_weights(food)
    if p in SIZE_WORDS:
        return w.get(p) or w.get(COUNT)
    if p in COUNTISH and p != "piece":
        return w.get(p)
    if p == "piece" and "piece" in w:
        return w["piece"]
    if _is_plain(p) or p == "piece":
        size = size_hint(hint)
        if size and size in w:
            return w[size]
        return next((w[k] for k in (COUNT, "medium", "large", "small") if k in w), None)
    return w.get(p) if p in WEIGHT_UNITS else None


def unit_label(unit, grams):
    """"clove (3 g)", "count (50 g)": a weight unit as the picker shows it."""
    g = round(grams, 1) if grams < 10 else round(grams)
    return f"{LABELS.get(unit, unit)} ({g:g} g)"


def _profile(food):
    """Return (label unit, label amount, grams, grams estimated, ml, ml estimated) per serving."""
    unit = parse_unit(food.get("serving_unit"))
    amount = _pos(food.get("serving_amount"))
    if amount is None:
        raise ValueError("Food has no valid serving_amount")
    sg, sml = _pos(food.get("serving_g")), _pos(food.get("serving_ml"))
    # The label's own grams and ml always win. Only the missing family is estimated: with the typical density of the food when its
    # name matches a keyword (density), else 1 g per ml.
    # A volume row of the food (food_units, issue #45: one cup chopped is 160 g from USDA, exact) comes before the keyword density.
    d, dest = None, True
    if not (sg and sml):
        vr = _volume_row(food)
        if vr:
            d, dest = vr["grams"] / VOLUME[vr["unit"]], vr["estimated"]
        else:
            d = density(food)
    to_ml = (lambda grams: grams / d) if d else (lambda grams: grams)
    to_g = (lambda millilitres: millilitres * d) if d else (lambda millilitres: millilitres)
    g = ge = ml = mle = None
    if unit in MASS:
        g, ge = amount * MASS[unit], False
        ml, mle = (sml, False) if sml else (to_ml(g), dest)
    elif unit in VOLUME:
        ml, mle = amount * VOLUME[unit], False
        g, ge = (sg, False) if sg else (to_g(ml), dest)
    else:
        g, ml = sg, sml
        ge = mle = False
        if g and not ml:
            ml, mle = to_ml(g), dest
        elif ml and not g:
            g, ge = to_g(ml), dest
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
    if unit in (COUNT, BLANK) or unit in COUNTISH or is_custom(unit):  # a plain count: the label's count word, else label servings
        row = count_row(food, unit)  # one clove, can or large has a weight on this food (food_units or the typical table)
        if row:
            return amount * row["grams"] / g, bool(ge or row["estimated"])
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
    if label_unit != COUNT and not _is_measure(label_unit):  # a count only where one thing has a known weight (a count word label)
        out.append(entry(COUNT, 1.0, False))
    if g:  # units one thing of which has a weight (issue #45): clove (3 g), can (425 g), large (50 g)
        have = {e["unit"] for e in out}
        for unit, row in unit_weights(food).items():
            if unit in have or unit in VOLUME or (unit in (COUNT, *SIZE_WORDS) and not _is_measure(label_unit)):
                continue
            e = entry(unit, 1.0, bool(ge or row["estimated"]))
            e.update(label=unit_label(unit, row["grams"]), grams=row["grams"], source=row["source"], **({"note": row["note"]} if row.get("note") else {}))
            out.append(e)
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


# ---------- energy ----------
# Calories missing from a source are estimated from the macros (Atwater, fiber counted at about 2 kcal per g). This is the
# only place that does it: lookup (at import), core (read time for older foods and entries) and the food form all call it.
KJ_PER_KCAL = 4.184
KCAL_ZERO_FLOOR = 5.0  # a stored 0 next to macros worth less than this many kcal is a real (label rounded) 0


def estimate_kcal(carbs, protein, fat, fiber=None):
    """4 per g protein, 4 per g carbs without fiber, 2 per g fiber, 9 per g fat. None when no macro is known at all."""
    if carbs is None and protein is None and fat is None:
        return None
    c, p, f, fi = (float(v or 0) for v in (carbs, protein, fat, fiber))
    return 4 * p + 4 * max(c - fi, 0) + 2 * fi + 9 * f


def resolve_kcal(kcal, carbs, protein, fat, fiber=None):
    """(kcal, estimated). A real positive value always wins. Missing (None) or 0 next to macros worth at least
    KCAL_ZERO_FLOOR kcal counts as missing and gets the estimate; 0 beside zero or tiny macros stays a real 0."""
    est = estimate_kcal(carbs, protein, fat, fiber)
    if kcal is None:
        return (round(est, 2), True) if est else (0.0 if est is not None else None, False)
    if kcal == 0 and est is not None and est >= KCAL_ZERO_FLOOR:
        return round(est, 2), True
    return kcal, False


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


def count_weight(label_unit, unit):
    """True when a count-like unit (see is_countlike) has a known weight on a food with this label unit. A plain count (blank, count,
    piece, each) or a typed word needs a count word label (1 egg, 2 slice, 1 piece (40 g)); a package or fuzzy unit needs the label's
    own word (2 cloves on a 1 clove (3 g) label). A measure label (100 g, 1 cup, 1 serving) knows no count weight."""
    if _is_measure(label_unit):
        return False
    if unit in COUNTISH and unit not in PLAIN_COUNTS:
        return unit == label_unit
    return True


def grams(food, amount, unit):
    """Grams in amount of unit, rounded to 0.1, or None when the food's weight is unknown or only estimated, when the amount is
    already in grams, or when a count-like unit has no known weight on this food (2 cloves of a 100 g label are never 200 g)."""
    try:
        u = unit_or_blank(unit)
        servings, estimated = _convert(food, amount, u)
        label_unit, _, g, ge = _profile(food)[:4]
    except ValueError:
        return None
    row = count_row(food, u)
    if is_custom(u) and not same_word(u, label_unit) and not row:  # a typed unit is only counted like Count, so its weight is not known
        return None
    if is_countlike(u) and not same_word(u, label_unit) and not count_weight(label_unit, u) and not row:
        return None
    if u == "g" or not g or ge or estimated:
        return None
    return round(servings * g, 1)


# ---------- printed package sizes ----------
# "1 (15 oz) can black beans", "2 (8-ounce) packages cream cheese", "1 stick (113 g) butter", "1 can (14.5 oz) tomatoes" and
# "1 15-oz can": the size printed on one package is an exact weight or volume, so grams = count x printed size. A range
# (14 to 15 oz), a missing number or an unknown size unit is not a printed size: the line falls back to Check Amount.
_NUM = r"\d+(?:[.,]\d+)?(?:\s+\d+/\d+)?|\d+/\d+"
_SIZE_UNIT = r"fl\.?\s*oz\.?|fluid\s+ounces?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|kilograms?|kg|milliliters?|millilitres?|ml|liters?|litres?|l"
_PKG = "|".join(sorted({w for u in COUNTISH for w in (u, u + "s", u + "es")} | {"pkg", "pkgs", "pkt", "tin", "tins"}, key=len, reverse=True))
_SIZE = rf"(?P<size>{_NUM})\s*-?\s*(?P<su>{_SIZE_UNIT})"
_PRINTED = [
    re.compile(rf"^\s*(?P<n>{_NUM})\s*\(\s*(?:about\s+)?{_SIZE}\s*\)\s*(?P<pkg>{_PKG})\b", re.I),  # 1 (15 oz) can, 2 (8-ounce) packages
    re.compile(rf"^\s*(?P<n>{_NUM})\s+(?P<pkg>{_PKG})\s*\(\s*(?:about\s+)?{_SIZE}\s*\)", re.I),  # 1 stick (113 g), 1 can (14.5 oz)
    re.compile(rf"^\s*(?P<n>{_NUM})\s+{_SIZE}\s+(?P<pkg>{_PKG})\b", re.I),  # 1 15-oz can, 2 8 ounce packages
]


def _number(text):
    t = normalize_fractions(text).replace(",", ".").strip()
    parts = t.split()
    try:
        total = 0.0
        for part in parts:
            if "/" in part:
                n, d = part.split("/")
                total += float(n) / float(d)
            else:
                total += float(part)
    except (ValueError, ZeroDivisionError):
        return None
    return _pos(total)


def printed_size(text):
    """A printed package size at the start of an ingredient line: {"amount": packages, "unit": package or fuzzy unit,
    "size": per package, "size_unit": g, kg, oz, lb, ml, l or floz, "rest": the line after it}, else None."""
    t = str(text or "")
    for pat in _PRINTED:
        m = pat.match(t)
        if not m:
            continue
        n, size = _number(m.group("n")), _number(m.group("size"))
        su = known_unit(m.group("su"))
        pkg = known_unit(m.group("pkg"))
        if n is None or size is None or su not in (*MASS, *VOLUME) or pkg not in COUNTISH:
            return None
        return {"amount": n, "unit": pkg, "size": size, "size_unit": su, "rest": t[m.end():].strip(" ,")}
    return None


def pkg_size(amount, unit):
    """(size, size unit) of one package from stored or sent values, or None when either is missing or not a weight or volume."""
    a = _pos(amount)
    try:
        u = unit_or_blank(unit)
    except ValueError:
        return None
    return (a, u) if a is not None and u in (*MASS, *VOLUME) else None


def size_text(size, size_unit):
    """"15 oz", "113 g", "12 fl oz" for a printed size."""
    return f"{size:g} {LABELS.get(size_unit, size_unit)}"


def match_amount(food, amount, unit, custom=True, pkg=None, hint=None):
    """Amount and unit for a recipe line ("1 cup", "2 tbsp", "2" eggs) matched to food, without asking the user.

    Returns {"amount", "unit", "check"} (plus "estimated": True when only a typical density or the 1 g per ml guess reaches the
    unit, and "reason": "no_weight" when a count has no known weight) or None when the line has no amount (salt to taste).
    - pkg (size, size unit) is a printed package size ("1 (15 oz) can"): the line is amount x size in that unit and nothing else,
      so a printed weight is exact and never counted twice.
    - The line's own unit when the food reaches it at all, as the picker offers it: same unit, weight to weight, volume to
      volume, and weight to volume through the food's own density (serving_g and serving_ml). A unit reachable only through an
      estimated density is used too, with "estimated": True (the same math the picker uses).
    - A count-like unit (no unit, count, piece, a package or fuzzy unit, a typed word) converts only where one thing has a known
      weight (count_weight): a plain count uses the label's count word ("2 eggs" -> 2 egg), a package or fuzzy unit the label's own
      word. Anything else (2 cloves of a 100 g label) is one label serving with check True and reason no_weight (no_size for a package
      unit such as 1 can), never label servings.
    - custom=False (Claude and Search proposals) never returns a custom unit: a typed word that is not the label's own becomes a plain count.
    - A known measure that cannot be reached (a cup of a food with no volume, no weight) is unreachable:
      one label serving with check True and reason no_convert, so the user confirms the amount."""
    a = _pos(amount)
    if a is None:
        return None
    label_unit, label_amount = _profile(food)[:2]
    try:
        u = unit_or_blank(unit) or None
    except ValueError:
        u = None
    size = pkg_size(*pkg) if pkg else None
    mine = count_row(food, u, hint) if u is not None and is_countlike(u) else None
    if size and (u is None or is_countlike(u)) and not (mine and mine["source"] == "user"):  # only the user's own weight beats a printed size
        return match_amount(food, round(a * size[0], 6), size[1], custom=False)
    if u is not None and not custom and is_custom(u) and not same_word(u, label_unit):
        u = None
    no_weight = {"amount": label_amount, "unit": label_unit, "check": True, "reason": NO_SIZE if u in PACKAGE_UNITS else NO_WEIGHT}
    if u is None or is_countlike(u):
        if u is not None and same_word(u, label_unit):
            return {"amount": a, "unit": label_unit, "check": False}
        row = count_row(food, u, hint)
        if row:  # one of the line's unit has a weight on this food: the line keeps its unit, the source is named
            est = row["estimated"] or _profile(food)[3]
            return {"amount": a, "unit": row["unit"], "check": False, **({"estimated": True} if est else {}), "source": row["source"]}
        if not count_weight(label_unit, u or COUNT):
            return no_weight
        if u is not None and is_custom(u) and parse_unit(u) not in PLAIN_COUNTS:
            return {"amount": a, "unit": u, "check": False}  # the user's own word on a count label counts like the label's word
        return {"amount": a, "unit": label_unit, "check": False}
    for entry in available_units(food):
        if entry["unit"] == u:
            return {"amount": a, "unit": u, "check": False, **({"estimated": True} if entry["estimated"] else {})}
    return {"amount": label_amount, "unit": label_unit, "check": True, "reason": NO_CONVERT}


def estimate_source(food, unit=None):
    """Where an estimated conversion comes from: the source of the unit's weight row (table, ai, user, fdc, off) when a count-like
    unit converts through one, else the source of the food's volume row, else "density" (a typical density of the food,
    GRAMS_PER_CUP) or "guess" (1 g per ml)."""
    row = count_row(food, unit) if unit is not None else None
    if row:
        return row["source"]
    vr = _volume_row(food)
    if vr:
        return vr["source"]
    return "density" if density(food) else "guess"


def weight_info(food, unit):
    """(source, note) of the food_units row a count-like unit converts through on this food, else (None, None)."""
    row = count_row(food, unit)
    return (row["source"], row.get("note")) if row else (None, None)
