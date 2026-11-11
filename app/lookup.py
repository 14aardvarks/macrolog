"""Food lookup over the network: Open Food Facts first, then USDA FoodData Central.

Every result is a Food dict with nutrients per LABEL serving. Network errors never
raise, they become notes. Tests replace `_transport` with an httpx.MockTransport.
"""
from __future__ import annotations

import re
from fractions import Fraction

import httpx

from . import config
from .units import MASS, VOLUME, parse_unit

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "code,product_name,generic_name,brands,serving_size,serving_quantity,serving_quantity_unit,nutriments"
FDC_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USER_AGENT = "macrolog/0.1"
FDC_NUTRIENTS = {"208": "kcal", "205": "carbs", "203": "protein", "204": "fat", "291": "fiber"}
_transport = None  # tests set an httpx.MockTransport here


def _client():
    return httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}, transport=_transport)


def _f(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


# ---------- barcodes ----------

def check_digit(body):
    """GS1 mod-10 check digit for a body without its last digit."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def expand_upce(code):
    """Expand an 8 digit UPC-E (number system 0 or 1) to its 12 digit UPC-A."""
    n, d, check = code[0], code[1:7], code[7]
    last = d[5]
    if last in "012":
        body = n + d[:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = n + d[:3] + "00000" + d[3:5]
    elif last == "4":
        body = n + d[:4] + "00000" + d[4]
    else:
        body = n + d[:5] + "0000" + last
    return body + check


def _normalize_8(digits):
    """8 digit codes: UPC-E (starts with 0 or 1) or EAN-8. Returns (candidates, valid, note)."""
    ean8 = [digits.zfill(13), digits]
    if digits[0] in "01":
        upca = expand_upce(digits)
        if check_digit(upca[:-1]) == int(upca[-1]):
            return [upca, upca.zfill(13), upca.zfill(14), ean8[0]], True, "UPC-E code expanded to UPC-A"
    expected = check_digit(digits[:-1])
    if expected == int(digits[-1]):
        return ean8, True, ""
    return ean8, False, f"Check digit is wrong (expected {expected}), probably a typo"


def normalize_barcode(raw):
    """Return {"candidates", "valid", "note"}. Candidates are 12, 13 and 14 digit spellings of one code
    (8 digit UPC-E and EAN-8 codes are expanded or padded)."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits and len(digits) == 8:
        cands, valid, note = _normalize_8(digits)
        return {"candidates": cands, "valid": valid, "note": note}
    if len(digits) not in (11, 12, 13, 14):
        note = "No digits found" if not digits else f"Barcode has {len(digits)} digits, expected 8 or 11 to 14"
        return {"candidates": [], "valid": False, "note": note}
    note, valid = "", True
    if len(digits) == 11:
        digits += str(check_digit(digits))
        note = "Check digit was missing and has been added"
    elif check_digit(digits[:-1]) != int(digits[-1]):
        valid = False
        note = f"Check digit is wrong (expected {check_digit(digits[:-1])}), probably a typo"
    core = digits.lstrip("0")
    cands = [core.zfill(w) for w in (12, 13, 14) if len(core) <= w]
    return {"candidates": cands, "valid": valid, "note": note}


# ---------- serving text ----------

_NUM = r"\d+\s+\d+/\d+|\d+/\d+|\d*\.?\d+"
_MAIN = re.compile(rf"^\s*(?:about|approx\.?|approximately|~)?\s*({_NUM})\s*(fl(?:uid)?\.?\s*(?:oz|ounces?)\b|[a-zA-Z]+)", re.I)
_METRIC = re.compile(r"(\d*\.?\d+)\s*(g|gm|grams?|ml|mls|milliliters?|millilitres?)\b", re.I)
_VULGAR = {"½": " 1/2", "¼": " 1/4", "¾": " 3/4", "⅓": " 1/3", "⅔": " 2/3"}


def _amount(text):
    parts = text.split()
    return sum(float(Fraction(p)) for p in parts)


def parse_serving(text, serving_g=None, serving_ml=None):
    """Turn printed serving text like "2 tbsp (30g)" into amount, unit, grams, ml and label_text."""
    label = " ".join(str(text or "").split())
    clean = label
    for ch, rep in _VULGAR.items():
        clean = clean.replace(ch, rep)
    m = _MAIN.match(clean)
    try:
        amount = _amount(m.group(1)) if m else None
    except ZeroDivisionError:
        amount = None
    if not m or not amount:
        # Nothing parsable: fall back to whatever metric size we were given.
        if serving_g:
            amount, unit, label = serving_g, "g", label or f"{serving_g:g} g"
        elif serving_ml:
            amount, unit, label = serving_ml, "ml", label or f"{serving_ml:g} ml"
        else:
            amount, unit, label = 1.0, "serving", label or "1 serving"
        return {"serving_amount": amount, "serving_unit": unit,
                "serving_g": serving_g or None, "serving_ml": serving_ml or None, "label_text": label}
    unit = parse_unit(m.group(2))
    found = {"g": None, "ml": None}
    for num, u in _METRIC.findall(clean[m.end():]):
        key = "g" if u.lower().startswith("g") else "ml"
        found[key] = found[key] or float(num)
    # Priority: metric in parentheses, then caller supplied value, then computed from the main unit.
    g = found["g"] or serving_g or (amount * MASS[unit] if unit in MASS else None)
    ml = found["ml"] or serving_ml or (amount * VOLUME[unit] if unit in VOLUME else None)
    return {"serving_amount": amount, "serving_unit": unit, "serving_g": g, "serving_ml": ml, "label_text": label}


def _food(source, source_id, barcode, name, brand, sv, vals):
    return {"source": source, "source_id": source_id, "barcode": barcode, "name": name, "brand": brand,
            **sv, "kcal": vals["kcal"], "carbs": vals.get("carbs") or 0.0, "protein": vals.get("protein") or 0.0,
            "fat": vals.get("fat") or 0.0, "fiber": vals.get("fiber")}


def _round(vals):
    return {k: round(v, 2) for k, v in vals.items() if v is not None}


# ---------- Open Food Facts ----------

def _off_values(n, basis, use_serving=True):
    """Per serving nutrients: prefer *_serving, else scale *_100g by the serving size in g or ml."""
    def per(key):
        v = _f(n.get(f"{key}_serving")) if use_serving else None
        if v is None:
            v100 = _f(n.get(f"{key}_100g"))
            v = v100 * basis / 100 if v100 is not None and basis else None
        return v
    vals = {"carbs": per("carbohydrates"), "protein": per("proteins"), "fat": per("fat"), "fiber": per("fiber")}
    vals["kcal"] = per("energy-kcal")
    if vals["kcal"] is None and per("energy") is not None:  # kJ only
        vals["kcal"] = per("energy") / 4.184
    return {"kcal": None, **_round(vals)}


def off_food(code, p):
    """Build a Food from an OFF product, or None when it has no usable nutrition."""
    n = p.get("nutriments") or {}
    qty = _f(p.get("serving_quantity"))
    is_ml = str(p.get("serving_quantity_unit") or "").lower() == "ml"
    text = p.get("serving_size") or ("" if qty else "100 g")
    sv = parse_serving(text, None if is_ml else qty, qty if is_ml else None)
    vals = _off_values(n, sv["serving_g"] or sv["serving_ml"])
    if vals["kcal"] is None and not (sv["serving_g"] or sv["serving_ml"]):
        sv = parse_serving("100 g")  # count serving with no weight: fall back to per 100 g
        vals = _off_values(n, 100, use_serving=False)
    if vals["kcal"] is None:
        return None
    name = (p.get("product_name") or p.get("generic_name") or "Unknown product").strip()
    brand = (p.get("brands") or "").split(",")[0].strip() or None
    return _food("off", str(p.get("code") or code), code, name, brand, sv, vals)


async def _off(client, candidates, notes):
    for code in candidates:
        r = await client.get(OFF_URL.format(code=code), params={"fields": OFF_FIELDS})
        if r.status_code == 404:
            continue
        r.raise_for_status()
        data = r.json()
        if data.get("status") in (1, "success") and data.get("product"):
            food = off_food(candidates[0], data["product"])
            if food:
                return food
            notes.append("Open Food Facts has no nutrition data for this product")
            return None
    return None


# ---------- USDA FoodData Central ----------

def fdc_food(item, barcode=None):
    """Build a Food from an FDC search hit (values are per 100 g), or None without energy."""
    per100 = {}
    for fn in item.get("foodNutrients") or []:
        key, v = FDC_NUTRIENTS.get(str(fn.get("nutrientNumber") or "")), _f(fn.get("value"))
        if key and v is not None:
            per100.setdefault(key, v)
    if "kcal" not in per100:
        return None
    size = _f(item.get("servingSize"))
    metric = {"g": "g", "grm": "g", "ml": "ml", "mlt": "ml"}.get(str(item.get("servingSizeUnit") or "").lower())
    household = " ".join(str(item.get("householdServingFullText") or "").split())
    if size and metric:
        factor, metric_txt = size / 100, f"{size:g} {metric}"
        label = household or metric_txt
        if household and not re.search(r"\d\s*(g|ml)\b", household, re.I):
            label = f"{household} ({metric_txt})"
        sv = parse_serving(label, size if metric == "g" else None, size if metric == "ml" else None)
    else:
        factor, sv = 1.0, parse_serving("100 g")
    vals = _round({k: v * factor for k, v in per100.items()})
    desc = (item.get("description") or "Unknown").strip()
    name = desc.title() if desc.isupper() else desc
    brand = item.get("brandName") or item.get("brandOwner") or None
    return _food("fdc", str(item.get("fdcId")), barcode or item.get("gtinUpc") or None, name, brand, sv, vals)


def fdc_api_key():
    """Stored setting fdc_api_key, else FDC_API_KEY, else DEMO_KEY (also when set but empty)."""
    return str(config.get("fdc_api_key")).strip() or "DEMO_KEY"


def _fdc_params(**extra):
    return {"api_key": fdc_api_key(), **extra}


async def _fdc(client, candidates, notes):
    wanted = {c.lstrip("0") for c in candidates}
    r = await client.get(FDC_URL, params=_fdc_params(query=candidates[0].lstrip("0"), dataType="Branded", pageSize=25))
    r.raise_for_status()
    for item in r.json().get("foods") or []:
        if str(item.get("gtinUpc") or "").lstrip("0") in wanted:
            return fdc_food(item, candidates[0])
    return None


# ---------- public API ----------

async def barcode(raw):
    """Look a barcode up in Open Food Facts, then USDA branded foods. Never raises."""
    info = normalize_barcode(raw)
    if not info["candidates"]:
        return {"food": None, "note": info["note"], "valid": False}
    notes = [info["note"]] if info["note"] else []
    async with _client() as client:
        for name, fn in (("Open Food Facts", _off), ("USDA FoodData Central", _fdc)):
            try:
                food = await fn(client, info["candidates"], notes)
            except (httpx.HTTPError, ValueError):
                notes.append(f"{name} unreachable")
                continue
            if food:
                return {"food": food, "note": "; ".join(notes), "valid": info["valid"]}
    notes.append("Not found in Open Food Facts or USDA FoodData Central")
    return {"food": None, "note": "; ".join(notes), "valid": info["valid"]}


async def search(query, limit=8):
    """USDA FoodData Central text search. Returns [] on empty query or network trouble."""
    if not str(query or "").strip():
        return []
    try:
        async with _client() as client:
            r = await client.get(FDC_URL, params=_fdc_params(query=query.strip(), pageSize=limit))
            r.raise_for_status()
            foods = [fdc_food(i) for i in r.json().get("foods") or []]
    except (httpx.HTTPError, ValueError):
        return []
    return [f for f in foods if f][:limit]
