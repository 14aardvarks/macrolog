"""Core API: foods, entries, days, quick lists, favorites, meals, goals and settings.

Foods are shared by both users. Everything else is per user and every read, patch
and delete is limited to the caller's own rows. Entries snapshot the food name and
macros at log time, so later food changes never rewrite history.
"""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from . import db, deps, lookup, units

router = APIRouter(prefix="/api", dependencies=[Depends(deps.current_user)])
CurrentUser = Annotated[dict, Depends(deps.current_user)]

MEALS = ("breakfast", "lunch", "dinner", "snack")
SCREENS = ("today", "scan", "search", "ai")
SOURCES = ("off", "fdc", "custom", "ai")
MACROS = ("kcal", "carbs", "protein", "fat")
# Micronutrients per label serving: (label, unit, default daily target, kind). A goal is a minimum to reach, a limit a
# maximum to stay under. Null means unknown, never zero. fiber was there from the start, the rest were added later.
MICRO_INFO = {
    "fiber": ("Fiber", "g", 28, "goal"), "sugars": ("Sugars", "g", 50, "limit"),
    "saturated_fat": ("Saturated Fat", "g", 20, "limit"), "sodium": ("Sodium", "mg", 2300, "limit"),
    "cholesterol": ("Cholesterol", "mg", 300, "limit"), "potassium": ("Potassium", "mg", 4700, "goal"),
    "calcium": ("Calcium", "mg", 1300, "goal"), "iron": ("Iron", "mg", 18, "goal"), "vitamin_d": ("Vitamin D", "mcg", 20, "goal")}
MICROS = tuple(MICRO_INFO)
NEW_MICROS = MICROS[1:]
FOOD_COLS = ("id", "source", "source_id", "barcode", "name", "brand", "serving_amount", "serving_unit",
             "serving_g", "serving_ml", "label_text", "kcal", "carbs", "protein", "fat", *MICROS)
ENTRY_COLS = ("id", "day", "meal", "food_id", "name", "brand", "amount", "unit", "servings",
              "kcal", "carbs", "protein", "fat", *MICROS)
DEFAULT_GOALS = {"kcal": 3000, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20}
GOAL_KEYS = {"carbs": ("carb_pct", 4), "protein": ("protein_pct", 4), "fat": ("fat_pct", 9)}  # pct key, kcal per g

SCHEMA = """
CREATE TABLE IF NOT EXISTS foods(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT,
  name TEXT NOT NULL, brand TEXT, serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL,
  serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',
  kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, created_by INTEGER, UNIQUE(source, source_id));
CREATE INDEX IF NOT EXISTS foods_barcode ON foods(barcode);
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL, meal TEXT,
  food_id INTEGER REFERENCES foods(id) ON DELETE SET NULL, name TEXT NOT NULL, brand TEXT,
  amount REAL NOT NULL, unit TEXT NOT NULL, servings REAL NOT NULL,
  kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS entries_user_day ON entries(user_id, day);
CREATE TABLE IF NOT EXISTS favorites(
  user_id INTEGER NOT NULL REFERENCES users(id), food_id INTEGER NOT NULL REFERENCES foods(id),
  PRIMARY KEY(user_id, food_id));
CREATE TABLE IF NOT EXISTS last_used(
  user_id INTEGER NOT NULL REFERENCES users(id), food_id INTEGER NOT NULL REFERENCES foods(id),
  amount REAL NOT NULL, unit TEXT NOT NULL, used_at TEXT NOT NULL, PRIMARY KEY(user_id, food_id));
CREATE TABLE IF NOT EXISTS meals(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, meal TEXT);
CREATE TABLE IF NOT EXISTS meal_items(
  id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
  food_id INTEGER NOT NULL REFERENCES foods(id), amount REAL NOT NULL, unit TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS favorite_tags(
  user_id INTEGER NOT NULL, food_id INTEGER NOT NULL, meal TEXT NOT NULL, PRIMARY KEY(user_id, food_id, meal));
CREATE TABLE IF NOT EXISTS recipe_tags(
  meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE, meal TEXT NOT NULL, PRIMARY KEY(meal_id, meal));
CREATE TABLE IF NOT EXISTS recipe_logs(
  id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE, meal TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hidden_foods(
  user_id INTEGER NOT NULL, food_id INTEGER NOT NULL, PRIMARY KEY(user_id, food_id));
CREATE TABLE IF NOT EXISTS goals(
  user_id INTEGER PRIMARY KEY REFERENCES users(id), kcal REAL NOT NULL,
  carb_pct REAL NOT NULL, protein_pct REAL NOT NULL, fat_pct REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings(
  user_id INTEGER PRIMARY KEY REFERENCES users(id), start_screen TEXT NOT NULL DEFAULT 'today',
  default_meal TEXT, use_last INTEGER NOT NULL DEFAULT 1,
  confirm_ai INTEGER NOT NULL DEFAULT 1, amount_format TEXT NOT NULL DEFAULT 'fraction');
CREATE TABLE IF NOT EXISTS micro_targets(
  user_id INTEGER NOT NULL REFERENCES users(id), nutrient TEXT NOT NULL, target REAL NOT NULL, PRIMARY KEY(user_id, nutrient));
"""
# Display switches in the settings table. Every default keeps the screens as they were before the switches existed;
# the new Micro Nutrients section starts collapsed. micros_hidden is a comma list of hidden nutrients.
DISPLAY_FLAGS = {"show_macros": 1, "show_micros": 1, "show_split": 1, "show_macro_bar": 1, "micros_open": 0}


def init(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)
    if "created_by" not in {r[1] for r in c.execute("PRAGMA table_info(foods)")}:  # databases made before My foods
        c.execute("ALTER TABLE foods ADD COLUMN created_by INTEGER")
    if "meal" not in {r[1] for r in c.execute("PRAGMA table_info(meals)")}:  # databases made before recipes had a meal
        c.execute("ALTER TABLE meals ADD COLUMN meal TEXT")
    if "use_last" not in {r[1] for r in c.execute("PRAGMA table_info(settings)")}:  # databases made before use_last
        c.execute("ALTER TABLE settings ADD COLUMN use_last INTEGER NOT NULL DEFAULT 1")
    cols = {r[1] for r in c.execute("PRAGMA table_info(settings)")}
    if "confirm_ai" not in cols:  # databases made before the Claude cost notice
        c.execute("ALTER TABLE settings ADD COLUMN confirm_ai INTEGER NOT NULL DEFAULT 1")
    if "amount_format" not in cols:  # databases made before fractions or decimals
        c.execute("ALTER TABLE settings ADD COLUMN amount_format TEXT NOT NULL DEFAULT 'fraction'")
    for key, default in DISPLAY_FLAGS.items():  # databases made before the Display settings
        if key not in cols:
            c.execute(f"ALTER TABLE settings ADD COLUMN {key} INTEGER NOT NULL DEFAULT {default}")
    if "micros_hidden" not in cols:
        c.execute("ALTER TABLE settings ADD COLUMN micros_hidden TEXT NOT NULL DEFAULT ''")
    for table in ("foods", "entries"):  # databases made before micronutrients: old rows stay null (unknown)
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for key in NEW_MICROS:
            if key not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {key} REAL")


# ---------- validation helpers ----------

def bad(msg: str) -> HTTPException:
    return HTTPException(400, msg)


def number(v, name: str, positive: bool = False, optional: bool = False):
    """Parse a finite number. Negative values are never allowed, zero only when not positive."""
    if v is None or v == "":
        if optional:
            return None
        raise bad(f"{name} is required")
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        raise bad(f"{name} must be a number")
    if isinstance(v, bool) or not math.isfinite(x):
        raise bad(f"{name} must be a finite number")
    if x < 0 or (positive and x == 0):
        raise bad(f"{name} must be greater than zero" if positive else f"{name} must not be negative")
    return x


def whole_id(v, name: str) -> int:
    if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"[0-9]+", v))):
        raise bad(f"{name} must be a whole number id")
    return int(v)


def pick(v, allowed: tuple, name: str, nullable: bool = False):
    if v is None and nullable:
        return None
    if v not in allowed:
        raise bad(f"{name} must be one of {', '.join(allowed)}" + (" or null" if nullable else ""))
    return v


def day_str(v) -> str:
    """Validate YYYY-MM-DD. Missing falls back to the server's local date."""
    if v in (None, ""):
        return date.today().isoformat()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
            raise ValueError
        date.fromisoformat(v)
    except ValueError:
        raise bad("day must be a date like 2025-01-31")
    return v


def r1(x: float) -> float:
    return round(x, 1)


def r2(x: float) -> float:
    return round(x, 2)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ---------- foods ----------

def food_dict(row) -> dict:
    return {k: row[k] for k in FOOD_COLS}


def need_food(c, food_id) -> dict:
    row = c.execute("SELECT * FROM foods WHERE id=?", (food_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Food not found")
    return food_dict(row)


def normalize_food(raw: dict, sources: tuple = SOURCES) -> dict:
    """Validate a Food from a client or from lookup and return the clean dict to store. Raises 400."""
    name = str(raw.get("name") or "").strip()
    if not name:
        raise bad("name is required")
    source = raw.get("source") or "custom"
    pick(source, sources, "source")
    try:
        unit = units.parse_unit(raw.get("serving_unit"))
    except ValueError as e:
        raise bad(f"serving_unit: {e}")
    amount = number(raw.get("serving_amount"), "serving_amount", positive=True)
    food = {"source": source, "source_id": str(raw["source_id"]) if raw.get("source_id") else None,
            "name": name, "brand": str(raw.get("brand") or "").strip() or None,
            "serving_amount": amount, "serving_unit": unit,
            "serving_g": number(raw.get("serving_g"), "serving_g", optional=True) or None,
            "serving_ml": number(raw.get("serving_ml"), "serving_ml", optional=True) or None,
            "label_text": " ".join(str(raw.get("label_text") or "").split()) or f"{amount:g} {unit}"}
    for key in MICROS:
        food[key] = number(raw.get(key), key, optional=True)
    for key in MACROS:
        food[key] = number(raw.get(key), key)
    code = re.sub(r"\D", "", str(raw.get("barcode") or ""))
    cands = lookup.normalize_barcode(code)["candidates"]
    food["barcode"] = cands[0] if cands else (code or None)
    try:
        units.available_units(food)
    except ValueError as e:
        raise bad(str(e))
    return food


def save_food(c, f: dict) -> dict:
    """Insert a normalized food, or return the existing row with the same (source, source_id)."""
    cols = [k for k in FOOD_COLS if k != "id"]
    cur = c.execute(f"INSERT INTO foods({','.join(cols)}) VALUES({','.join('?' * len(cols))}) "
                    "ON CONFLICT(source, source_id) DO NOTHING", [f[k] for k in cols])
    if cur.rowcount:
        return need_food(c, cur.lastrowid)
    row = c.execute("SELECT * FROM foods WHERE source=? AND source_id=?", (f["source"], f["source_id"])).fetchone()
    return food_dict(row)


def check_amount_unit(food: dict, amount, unit) -> tuple[float, str]:
    """Amount must be positive and finite, unit must be one the food can convert to."""
    amount = number(amount, "amount", positive=True)
    try:
        unit = units.parse_unit(unit)
    except ValueError as e:
        raise bad(f"unit: {e}")
    allowed = [u["unit"] for u in units.available_units(food)]
    if unit not in allowed:
        raise bad(f"Unit '{unit}' is not available for this food. Choose one of: {', '.join(allowed)}")
    return amount, unit


def macros(food: dict, amount: float, unit: str) -> dict:
    """units.scale with stored rounding: servings 4 places, nutrients 2 places."""
    s = units.scale(food, amount, unit)
    out = {"servings": round(s["servings"], 4), "estimated": bool(s.get("estimated"))}
    for key in MACROS:
        out[key] = r2(s[key])
    for key in MICROS:  # scaled like the macros; unknown stays None
        v = food.get(key)
        out[key] = None if v is None else r2(float(v) * s["servings"])
    return out


def can_ask_ai(user_id: int | None = None) -> bool:
    try:
        from . import ai
        return bool(ai.enabled(user_id))
    except Exception:
        return False


def like_filter(q: str) -> tuple[str, list]:
    """AND of case-insensitive LIKE matches, one per word, over name and brand (wildcards escaped)."""
    words = q.lower().split()[:6]
    sql = " AND ".join("lower(f.name || ' ' || coalesce(f.brand, '')) LIKE ? ESCAPE '\\'" for _ in words)
    params = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]
    return sql, params


@router.get("/foods/barcode/{code}")
async def barcode(code: str, user: CurrentUser):
    info = lookup.normalize_barcode(code)
    ask = can_ask_ai(user["id"])
    if info["candidates"]:
        marks = ",".join("?" * len(info["candidates"]))
        with db.conn() as c:
            row = c.execute(f"SELECT * FROM foods WHERE barcode IN ({marks}) ORDER BY (source IN ('custom','ai')) DESC, id DESC LIMIT 1",
                            info["candidates"]).fetchone()
        if row:
            return {"food": food_dict(row), "note": "", "valid": info["valid"], "can_ask_ai": ask}
    res = await lookup.barcode(code)
    food, note = res.get("food"), res.get("note") or ""
    if food:
        try:
            with db.conn() as c:
                food = save_food(c, normalize_food(food))
        except HTTPException as e:
            food, note = None, f"Found a product but its data was unusable ({e.detail})"
    return {"food": food, "note": note, "valid": bool(res.get("valid")), "can_ask_ai": ask}


@router.get("/foods/search")
async def search_foods(user: CurrentUser, q: str = "", remote: int = 1):
    """Local and favorite foods, plus USDA results unless remote=0 (used while typing)."""
    q = q.strip()
    if not q:
        return {"results": []}
    where, params = like_filter(q)
    with db.conn() as c:
        favs = c.execute(f"SELECT f.* FROM favorites v JOIN foods f ON f.id=v.food_id "
                         f"WHERE v.user_id=? AND {where} ORDER BY f.name", [user["id"], *params]).fetchall()
        local = c.execute(f"SELECT f.* FROM foods f WHERE {where} ORDER BY length(f.name), f.name LIMIT 20",
                          params).fetchall()
    results = [food_dict(r) for r in favs]
    seen = {f["id"] for f in results}
    results += [f for f in map(food_dict, local) if f["id"] not in seen]
    if not remote:
        return {"results": results}
    seen = {f["id"] for f in results}
    found = await lookup.search(q)
    with db.conn() as c:
        for raw in found:
            try:
                saved = save_food(c, normalize_food(raw))
            except HTTPException:
                continue  # unusable remote data is skipped, not fatal
            if saved["id"] not in seen:
                seen.add(saved["id"])
                results.append(saved)
    return {"results": results}


@router.post("/foods")
def create_food(user: CurrentUser, body: dict = Body(...)):
    food = normalize_food(body, ("custom", "ai"))
    food["source_id"] = None
    with db.conn() as c:
        saved = save_food(c, food)
        c.execute("UPDATE foods SET created_by=? WHERE id=? AND created_by IS NULL", (user["id"], saved["id"]))
        return saved


@router.get("/foods/missing-nutrients")
def missing_nutrients(user: CurrentUser, date: str | None = None):
    """Ids of the foods I have logged (on `date` when given, else ever) that have a blank micronutrient, can be looked up
    again and that I may refresh (custom and AI foods only when I created them). Oldest food first."""
    uid = user["id"]
    where, args = "e.user_id=?", [uid]
    if date not in (None, ""):
        where, args = where + " AND e.day=?", [*args, day_str(date)]
    blank = " OR ".join(f"f.{k} IS NULL" for k in MICROS)
    with db.conn() as c:
        rows = c.execute(f"SELECT DISTINCT f.* FROM entries e JOIN foods f ON f.id=e.food_id WHERE {where} AND ({blank}) ORDER BY f.id",
                         args).fetchall()
    ids = [r["id"] for r in rows if (r["source"] not in ("custom", "ai") or r["created_by"] == uid) and lookup.refresh_kind(food_dict(r))]
    return {"ids": ids, "total": len(ids)}


@router.get("/foods/{food_id}")
def get_food(food_id: int, user: CurrentUser):
    with db.conn() as c:
        food = need_food(c, food_id)
        last = c.execute("SELECT amount, unit FROM last_used WHERE user_id=? AND food_id=?",
                         (user["id"], food_id)).fetchone()
        fav = c.execute("SELECT 1 FROM favorites WHERE user_id=? AND food_id=?", (user["id"], food_id)).fetchone()
    return {**food, "units": units.available_units(food), "favorite": bool(fav),
            "last": {"amount": last["amount"], "unit": last["unit"]} if last else None}


@router.get("/preview")
def preview(user: CurrentUser, food_id: int, amount: str = "", unit: str = ""):
    with db.conn() as c:
        food = need_food(c, food_id)
    amount, unit = check_amount_unit(food, amount, unit)
    return macros(food, amount, unit)


# ---------- entries ----------

def entry_dict(row) -> dict:
    return {k: row[k] for k in ENTRY_COLS}


def own_entry(c, uid: int, entry_id: int):
    row = c.execute("SELECT * FROM entries WHERE id=? AND user_id=?", (entry_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, "Entry not found")
    return row


def log_entry(c, uid: int, food: dict, amount: float, unit: str, day: str, meal) -> dict:
    """Insert a snapshot entry and update last_used. Inputs must already be validated."""
    m = macros(food, amount, unit)
    nutrients = (*MACROS, *MICROS)
    cur = c.execute(
        f"INSERT INTO entries(user_id,day,meal,food_id,name,brand,amount,unit,servings,{','.join(nutrients)}) "
        f"VALUES({','.join('?' * (9 + len(nutrients)))})",
        (uid, day, meal, food["id"], food["name"], food["brand"], amount, unit, m["servings"], *[m[k] for k in nutrients]))
    c.execute("INSERT INTO last_used(user_id,food_id,amount,unit,used_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(user_id,food_id) DO UPDATE SET amount=excluded.amount, unit=excluded.unit, "
              "used_at=excluded.used_at", (uid, food["id"], amount, unit, now()))
    c.execute("DELETE FROM hidden_foods WHERE user_id=? AND food_id=?", (uid, food["id"]))
    return entry_dict(c.execute("SELECT * FROM entries WHERE id=?", (cur.lastrowid,)).fetchone())


@router.post("/entries")
def add_entry(user: CurrentUser, body: dict = Body(...)):
    day, meal = day_str(body.get("day")), pick(body.get("meal"), MEALS, "meal", nullable=True)
    food_id = whole_id(body.get("food_id"), "food_id")
    with db.conn() as c:
        food = need_food(c, food_id)
        amount, unit = check_amount_unit(food, body.get("amount"), body.get("unit"))
        if meal:  # a favorite logged with a meal gets that meal tag (tags are never removed automatically)
            c.execute("INSERT INTO favorite_tags(user_id, food_id, meal) SELECT user_id, food_id, ? FROM favorites "
                      "WHERE user_id=? AND food_id=? ON CONFLICT DO NOTHING", (meal, user["id"], food["id"]))
        return log_entry(c, user["id"], food, amount, unit, day, meal)


@router.patch("/entries/{entry_id}")
def patch_entry(entry_id: int, user: CurrentUser, body: dict = Body(...)):
    if not {"amount", "unit", "meal"} & body.keys():
        raise bad("Nothing to update: send amount, unit or meal")
    sets: dict = {}
    if "meal" in body:
        sets["meal"] = pick(body["meal"], MEALS, "meal", nullable=True)
    with db.conn() as c:
        row = own_entry(c, user["id"], entry_id)
        if {"amount", "unit"} & body.keys():
            if row["food_id"] is None:
                raise bad("This entry's food no longer exists, so its amount cannot change")
            food = need_food(c, row["food_id"])
            amount, unit = check_amount_unit(food, body.get("amount", row["amount"]), body.get("unit", row["unit"]))
            sets.update(amount=amount, unit=unit, **macros(food, amount, unit))
            sets.pop("estimated")
        if sets:  # column names come from the fixed keys above, values are bound
            c.execute(f"UPDATE entries SET {', '.join(k + '=?' for k in sets)} WHERE id=? AND user_id=?",
                      [*sets.values(), entry_id, user["id"]])
        return entry_dict(own_entry(c, user["id"], entry_id))


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, user: CurrentUser):
    with db.conn() as c:
        own_entry(c, user["id"], entry_id)
        c.execute("DELETE FROM entries WHERE id=? AND user_id=?", (entry_id, user["id"]))
    return {"deleted": entry_id}


# ---------- goals, settings and the day view ----------

def read_goals(c, uid: int) -> dict:
    row = c.execute("SELECT kcal, carb_pct, protein_pct, fat_pct FROM goals WHERE user_id=?", (uid,)).fetchone()
    return tidy(dict(row)) if row else dict(DEFAULT_GOALS)


def tidy(d: dict) -> dict:
    """Show whole-valued floats as ints (3000.0 becomes 3000)."""
    return {k: int(v) if isinstance(v, float) and v.is_integer() else v for k, v in d.items()}


@router.get("/goals")
def get_goals(user: CurrentUser):
    with db.conn() as c:
        return read_goals(c, user["id"])


@router.put("/goals")
def put_goals(user: CurrentUser, body: dict = Body(...)):
    g = {"kcal": number(body.get("kcal"), "kcal", positive=True)}
    for key in ("carb_pct", "protein_pct", "fat_pct"):
        g[key] = number(body.get(key), key)
    total = g["carb_pct"] + g["protein_pct"] + g["fat_pct"]
    if abs(total - 100) > 0.01:
        raise bad(f"carb_pct, protein_pct and fat_pct must total 100 (they total {total:g})")
    with db.conn() as c:
        c.execute("INSERT INTO goals(user_id,kcal,carb_pct,protein_pct,fat_pct) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET kcal=excluded.kcal, carb_pct=excluded.carb_pct, "
                  "protein_pct=excluded.protein_pct, fat_pct=excluded.fat_pct",
                  (user["id"], g["kcal"], g["carb_pct"], g["protein_pct"], g["fat_pct"]))
        return read_goals(c, user["id"])


AMOUNT_FORMATS = ("fraction", "decimal")


def read_settings(c, uid: int) -> dict:
    row = c.execute("SELECT start_screen, default_meal, use_last, confirm_ai, amount_format FROM settings WHERE user_id=?",
                    (uid,)).fetchone()
    if not row:
        return {"start_screen": "today", "default_meal": None, "use_last": True, "confirm_ai": True, "amount_format": "fraction"}
    return {"start_screen": row["start_screen"], "default_meal": row["default_meal"], "use_last": bool(row["use_last"]),
            "confirm_ai": bool(row["confirm_ai"]), "amount_format": row["amount_format"]}


@router.get("/settings")
def get_settings(user: CurrentUser):
    with db.conn() as c:
        return read_settings(c, user["id"])


@router.put("/settings")
def put_settings(user: CurrentUser, body: dict = Body(...)):
    with db.conn() as c:
        s = read_settings(c, user["id"])
        if "start_screen" in body:
            s["start_screen"] = pick(body["start_screen"], SCREENS, "start_screen")
        if "default_meal" in body:
            s["default_meal"] = pick(body["default_meal"], MEALS, "default_meal", nullable=True)
        for key in ("use_last", "confirm_ai"):
            if key in body:
                if not isinstance(body[key], bool):
                    raise bad(f"{key} must be true or false")
                s[key] = body[key]
        if "amount_format" in body:
            s["amount_format"] = pick(body["amount_format"], AMOUNT_FORMATS, "amount_format")
        c.execute("INSERT INTO settings(user_id,start_screen,default_meal,use_last,confirm_ai,amount_format) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET start_screen=excluded.start_screen, "
                  "default_meal=excluded.default_meal, use_last=excluded.use_last, confirm_ai=excluded.confirm_ai, "
                  "amount_format=excluded.amount_format",
                  (user["id"], s["start_screen"], s["default_meal"], int(s["use_last"]), int(s["confirm_ai"]), s["amount_format"]))
        return s


# ---------- display settings and micronutrient targets ----------

def read_display(c, uid: int) -> dict:
    row = c.execute(f"SELECT {', '.join(DISPLAY_FLAGS)}, micros_hidden FROM settings WHERE user_id=?", (uid,)).fetchone()
    out = {k: bool(row[k]) if row else bool(v) for k, v in DISPLAY_FLAGS.items()}
    hidden = set((row["micros_hidden"] if row else "").split(","))
    out["micros_shown"] = [k for k in MICROS if k not in hidden]
    return out


@router.get("/settings/display")
def get_display(user: CurrentUser):
    with db.conn() as c:
        return read_display(c, user["id"])


@router.put("/settings/display")
def put_display(user: CurrentUser, body: dict = Body(...)):
    """Per user show/hide switches. Send any subset; micros_shown is the list of nutrients to show."""
    if not (set(DISPLAY_FLAGS) | {"micros_shown"}) & body.keys():
        raise bad("Nothing to update: send " + ", ".join(DISPLAY_FLAGS) + " or micros_shown")
    with db.conn() as c:
        d = read_display(c, user["id"])
        for key in DISPLAY_FLAGS:
            if key in body:
                if not isinstance(body[key], bool):
                    raise bad(f"{key} must be true or false")
                d[key] = body[key]
        if "micros_shown" in body:
            shown = body["micros_shown"]
            if not isinstance(shown, list) or any(k not in MICROS for k in shown):
                raise bad("micros_shown must be a list of " + ", ".join(MICROS))
            d["micros_shown"] = [k for k in MICROS if k in shown]
        cols = [*DISPLAY_FLAGS, "micros_hidden"]
        vals = [int(d[k]) for k in DISPLAY_FLAGS] + [",".join(k for k in MICROS if k not in d["micros_shown"])]
        c.execute("INSERT OR IGNORE INTO settings(user_id) VALUES(?)", (user["id"],))
        c.execute(f"UPDATE settings SET {', '.join(k + '=?' for k in cols)} WHERE user_id=?", [*vals, user["id"]])
        return read_display(c, user["id"])


def micro_targets(c, uid: int) -> dict:
    saved = {r["nutrient"]: r["target"] for r in c.execute("SELECT nutrient, target FROM micro_targets WHERE user_id=?", (uid,))}
    return {k: saved.get(k, MICRO_INFO[k][2]) for k in MICROS}


def micro_list(c, uid: int) -> dict:
    t = micro_targets(c, uid)
    return {"micros": [tidy({"key": k, "label": lbl, "unit": unit, "kind": kind, "default": d, "target": t[k]})
                       for k, (lbl, unit, d, kind) in MICRO_INFO.items()]}


@router.get("/goals/micros")
def get_micro_goals(user: CurrentUser):
    with db.conn() as c:
        return micro_list(c, user["id"])


@router.put("/goals/micros")
def put_micro_goals(user: CurrentUser, body: dict = Body(...)):
    """{"targets": {nutrient: daily amount}} for any subset of the nutrients. Kinds are fixed."""
    targets = body.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise bad("targets must be an object of nutrient: daily amount")
    clean = {}
    for k, v in targets.items():
        if k not in MICRO_INFO:
            raise bad(f"Unknown nutrient {k}. Use one of {', '.join(MICROS)}")
        clean[k] = number(v, k, positive=True)
        if clean[k] > 100000:
            raise bad(f"{k} must be at most 100000")
    with db.conn() as c:
        c.executemany("INSERT INTO micro_targets(user_id, nutrient, target) VALUES(?,?,?) "
                      "ON CONFLICT(user_id, nutrient) DO UPDATE SET target=excluded.target",
                      [(user["id"], k, v) for k, v in clean.items()])
        return micro_list(c, user["id"])


def day_micros(rows, targets: dict) -> dict:
    """Per nutrient: total of the entries that have data, how many entries had data out of all, target and kind."""
    out = {}
    for k in MICROS:
        known = [r[k] for r in rows if r[k] is not None]
        total, target = sum(known), targets[k]
        out[k] = {"total": r1(total) if known else None, "known": len(known), "count": len(rows),
                  "target": int(target) if float(target).is_integer() else target, "kind": MICRO_INFO[k][3], "unit": MICRO_INFO[k][1],
                  "percent": math.floor(100 * total / target + 0.5) if known and target else 0}
    return out


@router.get("/day")
def get_day(user: CurrentUser, day: str | None = None):
    day = day_str(day)
    with db.conn() as c:
        rows = c.execute("SELECT * FROM entries WHERE user_id=? AND day=? ORDER BY id", (user["id"], day)).fetchall()
        goals = read_goals(c, user["id"])
        mtargets = micro_targets(c, user["id"])
    sums = {k: sum(r[k] or 0 for r in rows) for k in (*MACROS, "fiber")}
    targets = {"kcal": float(goals["kcal"])}
    for key, (pct, kcal_g) in GOAL_KEYS.items():
        targets[key] = goals["kcal"] * goals[pct] / 100 / kcal_g
    return {"day": day, "entries": [entry_dict(r) for r in rows],
            "totals": {k: r1(v) for k, v in sums.items()},
            "targets": {k: r1(v) for k, v in targets.items()},
            "percent": {k: math.floor(100 * sums[k] / targets[k] + 0.5) if targets[k] else 0 for k in MACROS},
            "remaining": {k: r1(targets[k] - sums[k]) for k in MACROS},
            "micros": day_micros(rows, mtargets)}


# ---------- quick lists and favorites ----------

def quick_item(food: dict, amount: float, unit: str, meal: str | None = None) -> dict:
    try:
        m = macros(food, amount, unit)
    except ValueError:  # stored unit no longer reachable: fall back to the label serving
        amount, unit = food["serving_amount"], units.parse_unit(food["serving_unit"])
        m = macros(food, amount, unit)
    return {"food": food, "amount": amount, "unit": unit, "servings": m["servings"],
            "kcal": m["kcal"], "protein": m["protein"], "meal": meal}


LAST_MEAL = "(SELECT e.meal FROM entries e WHERE e.user_id=lu.user_id AND e.food_id=f.id ORDER BY e.id DESC LIMIT 1) AS last_meal"


def items_from_rows(rows) -> dict:
    """Rows are foods joined with lu_amount, lu_unit and last_meal (null amount means never logged: use the label default).
    meal is the meal of the user's most recent entry of that food."""
    items = []
    for r in rows:
        food = food_dict(r)
        amount = r["lu_amount"] if r["lu_amount"] is not None else food["serving_amount"]
        unit = r["lu_unit"] or units.parse_unit(food["serving_unit"])
        items.append(quick_item(food, amount, unit, r["last_meal"]))
    return {"items": items}


@router.get("/quick/favorites")
def quick_favorites(user: CurrentUser):
    with db.conn() as c:
        rows = c.execute(
            "SELECT f.*, lu.amount AS lu_amount, lu.unit AS lu_unit, " + LAST_MEAL.replace("lu.user_id", "v.user_id") +
            " FROM favorites v JOIN foods f ON f.id=v.food_id "
            "LEFT JOIN last_used lu ON lu.food_id=f.id AND lu.user_id=v.user_id WHERE v.user_id=? "
            "ORDER BY (lu.used_at IS NULL), lu.used_at DESC, f.name", (user["id"],)).fetchall()
        out = items_from_rows(rows)
        tags, counts = favorite_tags(c, user["id"]), meal_counts(c, user["id"])
    for it in out["items"]:
        it["meals"], it["counts"] = tags.get(it["food"]["id"], []), counts.get(it["food"]["id"], {})
    return out


@router.get("/quick/recent")
def quick_recent(user: CurrentUser):
    with db.conn() as c:
        rows = c.execute(
            "SELECT f.*, lu.amount AS lu_amount, lu.unit AS lu_unit, " + LAST_MEAL +
            " FROM last_used lu JOIN foods f ON f.id=lu.food_id "
            "WHERE lu.user_id=? AND f.id NOT IN (SELECT food_id FROM hidden_foods WHERE user_id=lu.user_id) "
            "ORDER BY lu.used_at DESC, f.id DESC LIMIT 20", (user["id"],)).fetchall()
    return items_from_rows(rows)


@router.get("/quick/yesterday")
def quick_yesterday(user: CurrentUser, day: str | None = None):
    prev = (date.fromisoformat(day_str(day)) - timedelta(days=1)).isoformat()
    with db.conn() as c:
        entries = c.execute("SELECT food_id, amount, unit, meal FROM entries WHERE user_id=? AND day=? "
                            "AND food_id IS NOT NULL AND food_id NOT IN (SELECT food_id FROM hidden_foods WHERE user_id=?) ORDER BY id",
                            (user["id"], prev, user["id"])).fetchall()
        last: dict = {}  # last entry per distinct (food, meal) pair, in order of that last entry
        for e in entries:
            key = (e["food_id"], e["meal"])
            last.pop(key, None)
            last[key] = e
        items = [quick_item(need_food(c, fid), e["amount"], e["unit"], e["meal"]) for (fid, _), e in last.items()]
    return {"items": items}


def clean_tags(v) -> list[str]:
    """A list of meal names, de-duplicated and in breakfast..snack order."""
    if not isinstance(v, list):
        raise bad("meals must be a list of " + ", ".join(MEALS))
    for m in v:
        pick(m, MEALS, "meals")
    return [m for m in MEALS if m in v]


def favorite_tags(c, uid: int) -> dict:
    out: dict = {}
    for r in c.execute("SELECT t.food_id, t.meal FROM favorite_tags t JOIN favorites v ON v.user_id=t.user_id AND v.food_id=t.food_id "
                       "WHERE t.user_id=?", (uid,)):
        out.setdefault(r["food_id"], []).append(r["meal"])
    return {k: [m for m in MEALS if m in v] for k, v in out.items()}


def meal_counts(c, uid: int) -> dict:
    """{food_id: {meal: times the user logged it as that meal}}"""
    out: dict = {}
    for r in c.execute("SELECT food_id, meal, COUNT(*) n FROM entries WHERE user_id=? AND food_id IS NOT NULL AND meal IS NOT NULL "
                       "GROUP BY food_id, meal", (uid,)):
        out.setdefault(r["food_id"], {})[r["meal"]] = r["n"]
    return out


def own_favorite(c, uid: int, food_id: int) -> None:
    if not c.execute("SELECT 1 FROM favorites WHERE user_id=? AND food_id=?", (uid, food_id)).fetchone():
        raise HTTPException(404, "Favorite not found")


@router.put("/favorites/{food_id}/tags")
def put_favorite_tags(food_id: int, user: CurrentUser, body: dict = Body(...)):
    tags = clean_tags(body.get("meals"))
    with db.conn() as c:
        own_favorite(c, user["id"], food_id)
        c.execute("DELETE FROM favorite_tags WHERE user_id=? AND food_id=?", (user["id"], food_id))
        c.executemany("INSERT INTO favorite_tags(user_id, food_id, meal) VALUES(?,?,?)", [(user["id"], food_id, m) for m in tags])
    return {"food_id": food_id, "meals": tags}


@router.post("/saved/favorites/{food_id}/remove")
def remove_from_lists(food_id: int, user: CurrentUser):
    """Unfavorite, drop the tags and hide the food from Recent and Yesterday. Past entries are untouched."""
    with db.conn() as c:
        own_favorite(c, user["id"], food_id)
        for table in ("favorites", "favorite_tags"):
            c.execute(f"DELETE FROM {table} WHERE user_id=? AND food_id=?", (user["id"], food_id))
        c.execute("INSERT OR IGNORE INTO hidden_foods(user_id, food_id) VALUES(?,?)", (user["id"], food_id))
    return {"food_id": food_id, "removed": True}


@router.post("/favorites/{food_id}")
def add_favorite(food_id: int, user: CurrentUser):
    with db.conn() as c:
        need_food(c, food_id)
        c.execute("INSERT OR IGNORE INTO favorites(user_id, food_id) VALUES(?,?)", (user["id"], food_id))
        c.execute("DELETE FROM hidden_foods WHERE user_id=? AND food_id=?", (user["id"], food_id))
    return {"food_id": food_id, "favorite": True}


@router.delete("/favorites/{food_id}")
def remove_favorite(food_id: int, user: CurrentUser):
    with db.conn() as c:
        c.execute("DELETE FROM favorites WHERE user_id=? AND food_id=?", (user["id"], food_id))
    return {"food_id": food_id, "favorite": False}


# ---------- meals ----------

def parse_items(c, raw) -> list[tuple[dict, float, str]]:
    """Validate [{food_id, amount, unit}] and return (food, amount, unit) tuples."""
    if not isinstance(raw, list) or not raw:
        raise bad("items must be a non-empty list")
    out = []
    for i, it in enumerate(raw, 1):
        try:
            if not isinstance(it, dict):
                raise bad("must be an object with food_id, amount and unit")
            food = need_food(c, whole_id(it.get("food_id"), "food_id"))
            out.append((food, *check_amount_unit(food, it.get("amount"), it.get("unit"))))
        except HTTPException as e:
            raise HTTPException(e.status_code, f"item {i}: {e.detail}")
    return out


def meal_dict(c, row) -> dict:
    items = []
    for it in c.execute("SELECT * FROM meal_items WHERE meal_id=? ORDER BY position, id", (row["id"],)):
        food = need_food(c, it["food_id"])
        items.append({"food_id": food["id"], "food": food, "amount": it["amount"], "unit": it["unit"],
                      **macros(food, it["amount"], it["unit"])})
    tags = clean_tags([r["meal"] for r in c.execute("SELECT meal FROM recipe_tags WHERE meal_id=?", (row["id"],))])
    counts = {r["meal"]: r["n"] for r in c.execute("SELECT meal, COUNT(*) n FROM recipe_logs WHERE meal_id=? GROUP BY meal", (row["id"],))}
    return {"id": row["id"], "name": row["name"], "meal": tags[0] if tags else None, "meals": tags, "counts": counts,
            "items": items, "kcal": r1(sum(i["kcal"] for i in items))}


def save_meal(c, uid: int, name, items: list, meal: str | list | None = None) -> dict:
    """meal is one meal name, a list of meal names (the recipe tags), or None. meals.meal keeps the first tag."""
    tags = [meal] if isinstance(meal, str) else clean_tags(meal or [])
    cur = c.execute("INSERT INTO meals(user_id, name, meal) VALUES(?,?,?)", (uid, name, tags[0] if tags else None))
    c.executemany("INSERT INTO recipe_tags(meal_id, meal) VALUES(?,?)", [(cur.lastrowid, m) for m in tags])
    c.executemany("INSERT INTO meal_items(meal_id,food_id,amount,unit,position) VALUES(?,?,?,?,?)",
                  [(cur.lastrowid, f["id"], a, u, i) for i, (f, a, u) in enumerate(items)])
    return meal_dict(c, c.execute("SELECT * FROM meals WHERE id=?", (cur.lastrowid,)).fetchone())


def meal_name(body: dict) -> str:
    name = str(body.get("name") or "").strip()
    if not name:
        raise bad("name is required")
    return name


def own_meal(c, uid: int, meal_id: int):
    row = c.execute("SELECT * FROM meals WHERE id=? AND user_id=?", (meal_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, "Recipe not found")
    return row


@router.get("/meals")
def list_meals(user: CurrentUser):
    with db.conn() as c:
        rows = c.execute("SELECT * FROM meals WHERE user_id=? ORDER BY name COLLATE NOCASE, id", (user["id"],)).fetchall()
        return {"meals": [meal_dict(c, r) for r in rows]}


@router.post("/meals")
def create_meal(user: CurrentUser, body: dict = Body(...)):
    """Create a recipe from items. Tags come from meals (a list) or the older single meal."""
    name = meal_name(body)
    tags = clean_tags(body["meals"]) if "meals" in body else clean_tags([m for m in [pick(body.get("meal"), MEALS, "meal", nullable=True)] if m])
    with db.conn() as c:
        return save_meal(c, user["id"], name, parse_items(c, body.get("items")), tags)


def recipe_from_entries(uid: int, body: dict, only_meal: bool = False) -> dict:
    """Copy my entries of one day into a recipe. only_meal: the entries must be of body["meal"] and tag the recipe."""
    name, day = meal_name(body), day_str(body.get("day"))
    wanted = body.get("entry_ids")
    if wanted is not None and not isinstance(wanted, list):
        raise bad("entry_ids must be a list")
    meal = pick(body.get("meal"), MEALS, "meal", nullable=True) if only_meal else None
    with db.conn() as c:
        sql = "SELECT * FROM entries WHERE user_id=? AND day=? AND food_id IS NOT NULL" + (" AND meal IS ?" if only_meal else "")
        rows = c.execute(sql + " ORDER BY id", (uid, day, meal) if only_meal else (uid, day)).fetchall()
        if wanted is not None:
            ids = {whole_id(i, "entry_ids") for i in wanted}
            if ids - {r["id"] for r in rows}:
                raise bad("Some entry_ids are not entries of yours on that day" + (" and meal" if only_meal else ""))
            rows = [r for r in rows if r["id"] in ids]
        if not rows or (only_meal and wanted is None):
            raise bad("Pick at least one entry to save")
        items = [(need_food(c, r["food_id"]), r["amount"], r["unit"]) for r in rows]
        shared = {r["meal"] for r in rows}  # from-day: one meal for the whole recipe only when every entry agrees
        return save_meal(c, uid, name, items, meal if only_meal else (shared.pop() if len(shared) == 1 else None))


@router.post("/meals/from-day")
def meal_from_day(user: CurrentUser, body: dict = Body(...)):
    return recipe_from_entries(user["id"], body)


@router.post("/meals/from-meal")
def meal_from_meal(user: CurrentUser, body: dict = Body(...)):
    """Save chosen entries of one meal group (meal null = unassigned) as a recipe tagged with that meal."""
    return recipe_from_entries(user["id"], body, only_meal=True)


@router.patch("/meals/{meal_id}")
def patch_meal(meal_id: int, user: CurrentUser, body: dict = Body(...)):
    """Rename, retag (meals), or replace the items list (amounts, units, removed items)."""
    if not {"name", "meals", "items"} & body.keys():
        raise bad("Nothing to update: send name, meals or items")
    name = meal_name(body) if "name" in body else None
    tags = clean_tags(body["meals"]) if "meals" in body else None
    with db.conn() as c:
        own_meal(c, user["id"], meal_id)
        items = parse_items(c, body["items"]) if "items" in body else None
        if name:
            c.execute("UPDATE meals SET name=? WHERE id=?", (name, meal_id))
        if tags is not None:
            c.execute("DELETE FROM recipe_tags WHERE meal_id=?", (meal_id,))
            c.executemany("INSERT INTO recipe_tags(meal_id, meal) VALUES(?,?)", [(meal_id, m) for m in tags])
        if items is not None:
            c.execute("DELETE FROM meal_items WHERE meal_id=?", (meal_id,))
            c.executemany("INSERT INTO meal_items(meal_id,food_id,amount,unit,position) VALUES(?,?,?,?,?)",
                          [(meal_id, f["id"], a, u, i) for i, (f, a, u) in enumerate(items)])
        return meal_dict(c, own_meal(c, user["id"], meal_id))


@router.delete("/meals/{meal_id}")
def delete_meal(meal_id: int, user: CurrentUser):
    with db.conn() as c:
        own_meal(c, user["id"], meal_id)
        for table in ("meal_items", "recipe_tags", "recipe_logs"):
            c.execute(f"DELETE FROM {table} WHERE meal_id=?", (meal_id,))
        c.execute("DELETE FROM meals WHERE id=? AND user_id=?", (meal_id, user["id"]))
    return {"deleted": meal_id}


@router.post("/meals/{meal_id}/log")
def log_meal(meal_id: int, user: CurrentUser, body: dict | None = Body(None)):
    body = body or {}
    day, meal = day_str(body.get("day")), pick(body.get("meal"), MEALS, "meal", nullable=True)
    with db.conn() as c:
        row = own_meal(c, user["id"], meal_id)
        if body.get("items") is not None:  # the client's checklist replaces the saved items
            items = parse_items(c, body["items"])
        else:
            items = [(need_food(c, i["food_id"]), i["amount"], i["unit"]) for i in
                     c.execute("SELECT * FROM meal_items WHERE meal_id=? ORDER BY position, id", (row["id"],))]
        if meal:  # logging a recipe with a meal tags the recipe and counts toward that meal
            c.execute("INSERT OR IGNORE INTO recipe_tags(meal_id, meal) VALUES(?,?)", (meal_id, meal))
            c.execute("INSERT INTO recipe_logs(meal_id, meal) VALUES(?,?)", (meal_id, meal))
        return {"entries": [log_entry(c, user["id"], f, a, u, day, meal) for f, a, u in items]}


# ---------- saved screen: favorites, recipes and my foods ----------

NUTRITION = ("serving_amount", "serving_unit", "serving_g", "serving_ml", "kcal", "carbs", "protein", "fat", *MICROS)
FOOD_EDITABLE = ("name", "brand", "barcode", "label_text", *NUTRITION)
IN_USE = "(EXISTS(SELECT 1 FROM entries WHERE food_id=f.id) OR EXISTS(SELECT 1 FROM meal_items WHERE food_id=f.id))"


@router.get("/saved")
def get_saved(user: CurrentUser):
    uid = user["id"]
    with db.conn() as c:
        tags = favorite_tags(c, uid)
        favs = c.execute("SELECT f.* FROM favorites v JOIN foods f ON f.id=v.food_id WHERE v.user_id=? "
                         "ORDER BY f.name COLLATE NOCASE, f.id", (uid,)).fetchall()
        recipes = c.execute("SELECT * FROM meals WHERE user_id=? ORDER BY name COLLATE NOCASE, id", (uid,)).fetchall()
        mine = c.execute(f"SELECT f.*, {IN_USE} AS in_use FROM foods f WHERE f.created_by=? AND f.source IN ('custom','ai') "
                         "ORDER BY f.name COLLATE NOCASE, f.id", (uid,)).fetchall()
        return {"favorites": [{"food": food_dict(r), "meals": tags.get(r["id"], [])} for r in favs],
                "recipes": [meal_dict(c, r) for r in recipes],
                "foods": [{**food_dict(r), "in_use": bool(r["in_use"])} for r in mine]}


def own_food(c, uid: int, food_id: int):
    row = c.execute(f"SELECT f.*, {IN_USE} AS in_use FROM foods f WHERE f.id=?", (food_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Food not found")
    if row["created_by"] != uid or row["source"] not in ("custom", "ai"):
        raise HTTPException(403, "Only the person who created a custom food can change or delete it")
    return row


@router.patch("/foods/{food_id}")
def patch_food(food_id: int, user: CurrentUser, body: dict = Body(...)):
    """Edit my own custom food. Entries and recipes use the food live, so once it is used only the name,
    brand, barcode and label text can change; nutrition and serving stay as they were logged."""
    if not set(FOOD_EDITABLE) & body.keys():
        raise bad("Nothing to update")
    with db.conn() as c:
        row = own_food(c, user["id"], food_id)
        old = food_dict(row)
        new = normalize_food({**old, **{k: body[k] for k in FOOD_EDITABLE if k in body}}, (row["source"],))
        if row["in_use"] and any(new[k] != old[k] for k in NUTRITION):
            raise HTTPException(409, "This food is already in your log or a recipe, so its serving and nutrition can no longer change. "
                                     "You can still rename it.")
        cols = [k for k in FOOD_EDITABLE]
        c.execute(f"UPDATE foods SET {', '.join(k + '=?' for k in cols)} WHERE id=?", [new[k] for k in cols] + [food_id])
        return need_food(c, food_id)


def serving_ratio(old: dict, new: dict) -> float | None:
    """Factor that turns the source's per serving values into values for the stored serving, or None when the
    two servings cannot be compared (then nothing is copied)."""
    if old["serving_unit"] == new["serving_unit"] and abs(old["serving_amount"] - new["serving_amount"]) <= 0.01 * old["serving_amount"]:
        return 1.0
    for key in ("serving_g", "serving_ml"):
        if old.get(key) and new.get(key):
            return old[key] / new[key]
    return None


@router.post("/foods/{food_id}/refresh-nutrients")
async def refresh_nutrients(food_id: int, user: CurrentUser):
    """Look a saved food up again in its source and fill ONLY micronutrients that are null. Existing values,
    calories, macros and the name never change, so this is safe for foods already in logs or recipes.
    Foods from Open Food Facts or USDA are shared and any user may refresh them; custom and AI foods only by their creator."""
    with db.conn() as c:
        row = c.execute("SELECT id, source FROM foods WHERE id=?", (food_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Food not found")
        if row["source"] in ("custom", "ai"):
            own_food(c, user["id"], food_id)
        food = need_food(c, food_id)
    if lookup.refresh_kind(food) is None:
        raise bad("This food has no source ID or barcode, so there is nothing to look up")
    if all(food[k] is not None for k in MICROS):
        return {"food": food, "filled": [], "message": "This food already has every nutrient"}
    res = await lookup.refresh(food)
    if res.get("error") == "rate_limited":
        raise HTTPException(429, res["note"])
    if res.get("error"):
        raise HTTPException(502, res["note"])
    found = res.get("food")
    if not found:
        return {"food": food, "filled": [], "message": res.get("note") or "The source has no more data for this food"}
    ratio = serving_ratio(food, found)
    if ratio is None:
        raise HTTPException(409, "The source lists a different serving size, so its values were not copied")
    filled = []
    with db.conn() as c:
        for key in MICROS:
            v = found.get(key)
            if food[key] is None and isinstance(v, (int, float)) and v >= 0:
                if c.execute(f"UPDATE foods SET {key}=? WHERE id=? AND {key} IS NULL", (r2(v * ratio), food_id)).rowcount:
                    filled.append(key)
        updated = need_food(c, food_id)
    msg = "Filled " + ", ".join(MICRO_INFO[k][0].lower() for k in filled) if filled else "The source has no more data for this food"
    return {"food": updated, "filled": filled, "message": msg}


@router.delete("/foods/{food_id}")
def delete_food(food_id: int, user: CurrentUser):
    with db.conn() as c:
        row = own_food(c, user["id"], food_id)
        if row["in_use"]:
            raise HTTPException(409, "This food is in a log entry or a recipe, so it cannot be deleted.")
        if c.execute("SELECT 1 FROM favorites WHERE food_id=? AND user_id<>?", (food_id, user["id"])).fetchone():
            raise HTTPException(409, "Someone else has this food in their favorites, so it cannot be deleted.")
        for table in ("favorites", "favorite_tags", "hidden_foods", "last_used"):
            c.execute(f"DELETE FROM {table} WHERE food_id=?", (food_id,))
        c.execute("DELETE FROM foods WHERE id=?", (food_id,))
    return {"deleted": food_id}
