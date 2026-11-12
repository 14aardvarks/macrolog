"""Core API: foods, entries, days, quick lists, favorites, meals, goals and settings.

Foods are shared by both users. Everything else is per user and every read, patch
and delete is limited to the caller's own rows. Entries snapshot the food name and
macros at log time, so later food changes never rewrite history.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from . import db, deps, lookup, units

router = APIRouter(prefix="/api", dependencies=[Depends(deps.current_user)])
CurrentUser = Annotated[dict, Depends(deps.current_user)]

MEALS = ("breakfast", "lunch", "dinner", "snack", "dessert")
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
              "kcal", "carbs", "protein", "fat", *MICROS, "group_id")
DEFAULT_GOALS = {"kcal": 3000, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20}
GOAL_KEYS = {"carbs": ("carb_pct", 4), "protein": ("protein_pct", 4), "fat": ("fat_pct", 9)}  # pct key, kcal per g

# Recipe ingredients. food_id, amount and unit are null while an imported ingredient is not matched to a food yet;
# src_* keep what the recipe said ("1 1/2 cups flour, sifted"). skipped rows (salt to taste, water) count for nothing.
MEAL_ITEMS_BODY = """
  id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
  food_id INTEGER REFERENCES foods(id), amount REAL, unit TEXT, position INTEGER NOT NULL DEFAULT 0,
  src_text TEXT, src_amount REAL, src_unit TEXT, src_name TEXT, src_note TEXT, skipped INTEGER NOT NULL DEFAULT 0,
  needs_check INTEGER NOT NULL DEFAULT 0"""
# needs_check: a food is attached but its amount could not be worked out from the recipe line (for example "1 cup" of a
# food known only by weight). It counts for nothing, like an unmatched row, until the user confirms an amount.

SCHEMA = """
CREATE TABLE IF NOT EXISTS foods(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT,
  name TEXT NOT NULL, brand TEXT, serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL,
  serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',
  kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, created_by INTEGER, deleted INTEGER NOT NULL DEFAULT 0, UNIQUE(source, source_id));
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
CREATE TABLE IF NOT EXISTS meal_items({MEAL_ITEMS_BODY});
CREATE TABLE IF NOT EXISTS favorite_tags(
  user_id INTEGER NOT NULL, food_id INTEGER NOT NULL, meal TEXT NOT NULL, PRIMARY KEY(user_id, food_id, meal));
CREATE TABLE IF NOT EXISTS recipe_tags(
  meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE, meal TEXT NOT NULL, PRIMARY KEY(meal_id, meal));
CREATE TABLE IF NOT EXISTS recipe_logs(
  id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE, meal TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entry_groups(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL, meal TEXT, meal_id INTEGER,
  name TEXT NOT NULL, amount REAL NOT NULL, unit TEXT NOT NULL, fraction REAL NOT NULL, portions TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS hidden_foods(
  user_id INTEGER NOT NULL, food_id INTEGER NOT NULL, PRIMARY KEY(user_id, food_id));
CREATE TABLE IF NOT EXISTS deleted_foods(
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
DISPLAY_FLAGS = {"show_macros": 1, "show_micros": 1, "show_split": 1, "show_macro_bar": 1, "show_table": 1, "micros_open": 0}
TODAY_VIEWS = ("list", "table")  # the Today tab's default view, stored as settings.today_view
START_SOURCES = ("all", "off", "fdc", "ai")  # the Add search Source to start with, stored as settings.search_source
AUTO_MATCHES = ("search", "claude", "search_claude", "off")  # Auto-Match After Import: the free Search (default), Claude, Search then Claude for rows Search left without a proposal, or nothing; stored as settings.auto_match (plain TEXT, validated here, no schema change)
SCHEMA = SCHEMA.replace("{MEAL_ITEMS_BODY}", MEAL_ITEMS_BODY)


def migrate_meal_items(c: sqlite3.Connection) -> None:
    """Databases made before imported recipes have meal_items.food_id NOT NULL. SQLite cannot drop a NOT NULL, so the
    table is rebuilt once in one transaction (ids and positions kept). Safe to run again: it only acts on the old shape."""
    info = {r[1]: r for r in c.execute("PRAGMA table_info(meal_items)")}
    if "src_text" in info and not info["food_id"][3]:
        return
    c.commit()
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute("DROP TABLE IF EXISTS meal_items_new")
        c.execute(f"CREATE TABLE meal_items_new({MEAL_ITEMS_BODY})")
        c.execute("INSERT INTO meal_items_new(id, meal_id, food_id, amount, unit, position) "
                  "SELECT id, meal_id, food_id, amount, unit, position FROM meal_items")
        c.execute("DROP TABLE meal_items")
        c.execute("ALTER TABLE meal_items_new RENAME TO meal_items")
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def init(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)
    if "created_by" not in {r[1] for r in c.execute("PRAGMA table_info(foods)")}:  # databases made before My foods
        c.execute("ALTER TABLE foods ADD COLUMN created_by INTEGER")
    if "deleted" not in {r[1] for r in c.execute("PRAGMA table_info(foods)")}:  # databases made before soft delete
        c.execute("ALTER TABLE foods ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
    if "meal" not in {r[1] for r in c.execute("PRAGMA table_info(meals)")}:  # databases made before recipes had a meal
        c.execute("ALTER TABLE meals ADD COLUMN meal TEXT")
    if "servings" not in {r[1] for r in c.execute("PRAGMA table_info(meals)")}:  # databases made before imported recipes
        c.execute("ALTER TABLE meals ADD COLUMN servings REAL")
    if "steps" not in {r[1] for r in c.execute("PRAGMA table_info(meals)")}:  # databases made before recipe steps (JSON list, null = none)
        c.execute("ALTER TABLE meals ADD COLUMN steps TEXT")
    meal_cols = {r[1] for r in c.execute("PRAGMA table_info(meals)")}
    for col, kind in (("yield_amount", "REAL"), ("yield_unit", "TEXT")):  # databases made before the total yield (null = not set)
        if col not in meal_cols:
            c.execute(f"ALTER TABLE meals ADD COLUMN {col} {kind}")
    migrate_meal_items(c)
    if "needs_check" not in {r[1] for r in c.execute("PRAGMA table_info(meal_items)")}:  # databases made before Check Amount
        c.execute("ALTER TABLE meal_items ADD COLUMN needs_check INTEGER NOT NULL DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS meal_items_meal ON meal_items(meal_id, position)")
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
    if "today_view" not in cols:  # databases made before the Today View setting
        c.execute("ALTER TABLE settings ADD COLUMN today_view TEXT NOT NULL DEFAULT 'list'")
    if "search_source" not in cols:  # databases made before the Default Search Source setting
        c.execute("ALTER TABLE settings ADD COLUMN search_source TEXT NOT NULL DEFAULT 'all'")
    if "auto_match" not in cols:  # databases made before Auto-Match After Import
        c.execute("ALTER TABLE settings ADD COLUMN auto_match TEXT NOT NULL DEFAULT 'search'")
    for table in ("foods", "entries"):  # databases made before micronutrients: old rows stay null (unknown)
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for key in NEW_MICROS:
            if key not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {key} REAL")
    if "group_id" not in {r[1] for r in c.execute("PRAGMA table_info(entries)")}:  # databases made before recipe logs were grouped
        c.execute("ALTER TABLE entries ADD COLUMN group_id INTEGER")  # null: a plain entry, or one logged from a recipe before this
    c.execute("CREATE INDEX IF NOT EXISTS entries_group ON entries(group_id)")


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


# A deleted food is hidden, never removed: entries and recipe rows keep pointing at it, so history and totals never change.
# foods.deleted hides it from everyone (only set for a custom or Claude food its creator deleted when nobody else uses it);
# deleted_foods(user_id, food_id) hides it from one user (the rule for shared Open Food Facts and USDA foods).
# SQL fragment for a query over foods f, with one ? for the user id.
VISIBLE = "f.deleted=0 AND f.id NOT IN (SELECT food_id FROM deleted_foods WHERE user_id=?)"


def undelete(c, uid: int, food_id: int) -> None:
    """Bring a deleted food back as a normal food, for this user and (when it was deleted for everyone) for all."""
    c.execute("DELETE FROM deleted_foods WHERE user_id=? AND food_id=?", (uid, food_id))
    c.execute("UPDATE foods SET deleted=0 WHERE id=? AND deleted=1", (food_id,))


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
        return bool(ai.enabled(user_id)) and ai.feature_on("label")
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
            with db.conn() as c:
                undelete(c, user["id"], row["id"])  # scanning a deleted food again brings it back
            return {"food": food_dict(row), "note": "", "valid": info["valid"], "can_ask_ai": ask}
    res = await lookup.barcode(code)
    food, note = res.get("food"), res.get("note") or ""
    if food:
        try:
            with db.conn() as c:
                food = save_food(c, normalize_food(food))
                undelete(c, user["id"], food["id"])
        except HTTPException as e:
            food, note = None, f"Found a product but its data was unusable ({e.detail})"
    return {"food": food, "note": note, "valid": bool(res.get("valid")), "can_ask_ai": ask}


SEARCH_SOURCES = ("all", "off", "fdc")


@router.get("/foods/search")
async def search_foods(user: CurrentUser, q: str = "", remote: int = 1, source: str = "all"):
    """Local and favorite foods, plus remote results unless remote=0 (used while typing).
    source: all (local foods of any source, then USDA and Open Food Facts), off or fdc (that source only, local and remote)."""
    if source not in SEARCH_SOURCES:
        raise HTTPException(400, "source must be all, off or fdc")
    q = q.strip()
    if not q:
        return {"results": []}
    where, params = like_filter(q)
    if source != "all":
        where, params = f"{where} AND f.source=?", [*params, source]
    with db.conn() as c:
        favs = c.execute(f"SELECT f.* FROM favorites v JOIN foods f ON f.id=v.food_id "
                         f"WHERE v.user_id=? AND {where} AND {VISIBLE} ORDER BY f.name", [user["id"], *params, user["id"]]).fetchall()
        local = c.execute(f"SELECT f.* FROM foods f WHERE {where} AND {VISIBLE} ORDER BY length(f.name), f.name LIMIT 20",
                          [*params, user["id"]]).fetchall()
    results = [food_dict(r) for r in favs]
    seen = {f["id"] for f in results}
    results += [f for f in map(food_dict, local) if f["id"] not in seen]
    if not remote:
        return {"results": results}
    seen = {f["id"] for f in results}
    if source == "all":  # both at once, USDA first as before; each returns [] on trouble
        usda, off = await asyncio.gather(lookup.search(q), lookup.search_off(q))
        found = [*usda, *off]
    else:
        found = await (lookup.search(q) if source == "fdc" else lookup.search_off(q))
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
    start = units.default_pick(food)
    return {**food, "units": units.available_units(food), "default": {"amount": start[0], "unit": start[1]}, "favorite": bool(fav),
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


def log_entry(c, uid: int, food: dict, amount: float, unit: str, day: str, meal, group_id: int | None = None) -> dict:
    """Insert a snapshot entry and update last_used. Inputs must already be validated. group_id: the recipe log it belongs to."""
    m = macros(food, amount, unit)
    nutrients = (*MACROS, *MICROS)
    cur = c.execute(
        f"INSERT INTO entries(user_id,day,meal,food_id,name,brand,amount,unit,servings,group_id,{','.join(nutrients)}) "
        f"VALUES({','.join('?' * (10 + len(nutrients)))})",
        (uid, day, meal, food["id"], food["name"], food["brand"], amount, unit, m["servings"], group_id, *[m[k] for k in nutrients]))
    c.execute("INSERT INTO last_used(user_id,food_id,amount,unit,used_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(user_id,food_id) DO UPDATE SET amount=excluded.amount, unit=excluded.unit, "
              "used_at=excluded.used_at", (uid, food["id"], amount, unit, now()))
    c.execute("DELETE FROM hidden_foods WHERE user_id=? AND food_id=?", (uid, food["id"]))
    undelete(c, uid, food["id"])  # logging a deleted food again brings it back
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
        if row["group_id"] is not None and "meal" in sets and sets["meal"] != row["meal"]:
            sets["group_id"] = None  # one ingredient moved to another meal leaves its recipe log (the app moves whole groups)
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
        row = own_entry(c, user["id"], entry_id)
        c.execute("DELETE FROM entries WHERE id=? AND user_id=?", (entry_id, user["id"]))
        drop_empty_group(c, row["group_id"])
    return {"deleted": entry_id}


# ---------- recipe logs on Today ----------
# Logging a recipe writes one entry per ingredient, so totals, micronutrients and history stay exact, plus one entry_groups
# row that links them (entries.group_id): the recipe's name, the portion logged (amount and a unit of the recipe's portions,
# kept as a snapshot so the group can be rescaled after the recipe changes or is deleted) and its share of the whole recipe.
# /api/day shows each group as one item. Entries logged from a recipe before groups existed have no link and stay separate.

def drop_empty_group(c, gid) -> None:
    if gid is not None and not c.execute("SELECT 1 FROM entries WHERE group_id=? LIMIT 1", (gid,)).fetchone():
        c.execute("DELETE FROM entry_groups WHERE id=?", (gid,))


def new_group(c, uid: int, day: str, meal, meal_id, name: str, amount: float, unit: str, frac: float, plist: list) -> int:
    return c.execute("INSERT INTO entry_groups(user_id, day, meal, meal_id, name, amount, unit, fraction, portions) VALUES(?,?,?,?,?,?,?,?,?)",
                     (uid, day, meal, meal_id, name, amount, unit, frac, json.dumps(plist))).lastrowid


def group_portions(row) -> list:
    try:
        v = json.loads(row["portions"] or "[]")
    except ValueError:
        v = []
    return v if isinstance(v, list) and v else portions(1, None)


def day_entry(r) -> dict:
    return {**entry_dict(r), "kind": "food", "source": r["source"]}


def group_item(g, parts: list) -> dict:
    """One recipe log as an entry-like item with the summed nutrients of its ingredient rows (parts). A micronutrient is
    null when no part knows it. id is null so it is never mistaken for an entry id; group_id names it."""
    out = {"kind": "recipe", "id": None, "group_id": g["id"], "meal_id": g["meal_id"], "day": g["day"], "meal": g["meal"],
           "name": g["name"], "brand": None, "food_id": None, "source": None, "amount": g["amount"], "unit": g["unit"],
           "fraction": g["fraction"], "servings": None, "portions": group_portions(g), "parts": parts}
    for k in MACROS:
        out[k] = r2(sum(p[k] or 0 for p in parts))
    for k in MICROS:
        known = [p[k] for p in parts if p[k] is not None]
        out[k] = r2(sum(known)) if known else None
    return out


def day_items(c, uid: int, rows) -> list:
    """A day's entries as Today lists them: plain entries, and one item per recipe log in the place of its first ingredient."""
    gids = sorted({r["group_id"] for r in rows if r["group_id"] is not None})
    groups = {}
    if gids:
        marks = ",".join("?" * len(gids))
        groups = {g["id"]: g for g in c.execute(f"SELECT * FROM entry_groups WHERE user_id=? AND id IN ({marks})", (uid, *gids))}
    order, parts = [], {}
    for r in rows:
        g = groups.get(r["group_id"])
        if g is None:
            order.append(day_entry(r))
            continue
        if g["id"] not in parts:
            parts[g["id"]] = []
            order.append(g)
        parts[g["id"]].append(day_entry(r))
    return [x if isinstance(x, dict) else group_item(x, parts[x["id"]]) for x in order]


def own_group(c, uid: int, gid: int):
    row = c.execute("SELECT * FROM entry_groups WHERE id=? AND user_id=?", (gid, uid)).fetchone()
    if not row:
        raise HTTPException(404, "Recipe log not found")
    return row


def group_out(c, uid: int, gid: int) -> dict:
    g = own_group(c, uid, gid)
    rows = c.execute("SELECT e.*, f.source AS source FROM entries e LEFT JOIN foods f ON f.id=e.food_id "
                     "WHERE e.user_id=? AND e.group_id=? ORDER BY e.id", (uid, gid)).fetchall()
    if not rows:
        raise HTTPException(404, "Recipe log not found")
    return group_item(g, [day_entry(r) for r in rows])


def portion_body(g, body: dict) -> tuple[float, str, float]:
    """amount and unit (one of the group's portions) of a PATCH or copy body: (amount, unit, share of the whole recipe)."""
    plist = group_portions(g)
    unit = body.get("unit", g["unit"])
    frac = recipe_fraction({"portions": plist}, body.get("amount", g["amount"]), unit)
    return float(body.get("amount", g["amount"])), unit, frac


def scaled_nutrients(c, row, k: float) -> dict:
    """An ingredient row at k times its amount: worked out again from its food like PATCH /api/entries, or the snapshot scaled
    when the food row is gone or its unit can no longer be reached."""
    amount = round(row["amount"] * k, 4)
    food = c.execute("SELECT * FROM foods WHERE id=?", (row["food_id"],)).fetchone() if row["food_id"] is not None else None
    if food is not None:
        try:
            m = macros(food_dict(food), amount, row["unit"])
            m.pop("estimated")
            return {"amount": amount, **m}
        except ValueError:
            pass
    return {"amount": amount, "servings": round(row["servings"] * k, 4),
            **{key: None if row[key] is None else r2(row[key] * k) for key in (*MACROS, *MICROS)}}


@router.get("/entry-groups/{group_id}")
def get_group(group_id: int, user: CurrentUser):
    with db.conn() as c:
        return group_out(c, user["id"], group_id)


@router.patch("/entry-groups/{group_id}")
def patch_group(group_id: int, user: CurrentUser, body: dict = Body(...)):
    """Change how much of the recipe was logged (amount and unit of its portions; every ingredient row is rescaled by the same
    factor) and or the meal (the whole group moves)."""
    if not {"amount", "unit", "meal"} & body.keys():
        raise bad("Nothing to update: send amount, unit or meal")
    meal = pick(body["meal"], MEALS, "meal", nullable=True) if "meal" in body else None
    uid = user["id"]
    with db.conn() as c:
        g = own_group(c, uid, group_id)
        if {"amount", "unit"} & body.keys():
            amount, unit, frac = portion_body(g, body)
            k = frac / g["fraction"] if g["fraction"] else 1.0
            for row in c.execute("SELECT * FROM entries WHERE user_id=? AND group_id=?", (uid, group_id)).fetchall():
                sets = scaled_nutrients(c, row, k)
                c.execute(f"UPDATE entries SET {', '.join(key + '=?' for key in sets)} WHERE id=?", [*sets.values(), row["id"]])
            c.execute("UPDATE entry_groups SET amount=?, unit=?, fraction=? WHERE id=?", (amount, unit, frac, group_id))
        if "meal" in body:
            c.execute("UPDATE entry_groups SET meal=? WHERE id=?", (meal, group_id))
            c.execute("UPDATE entries SET meal=? WHERE user_id=? AND group_id=?", (meal, uid, group_id))
        return group_out(c, uid, group_id)


@router.delete("/entry-groups/{group_id}")
def delete_group(group_id: int, user: CurrentUser):
    """Remove a recipe log: every ingredient row of it."""
    with db.conn() as c:
        own_group(c, user["id"], group_id)
        c.execute("DELETE FROM entries WHERE user_id=? AND group_id=?", (user["id"], group_id))
        c.execute("DELETE FROM entry_groups WHERE id=?", (group_id,))
    return {"deleted": group_id}


@router.post("/entry-groups/{group_id}/copy")
def copy_group(group_id: int, user: CurrentUser, body: dict | None = Body(None)):
    """Log a recipe log again (Yesterday on Add) as one new group: the same ingredient rows, on day and meal, optionally at
    another amount and unit of its portions. Counts as a log of the recipe when it still exists, like POST /api/meals/{id}/log."""
    body = body or {}
    day = day_str(body.get("day"))
    uid = user["id"]
    with db.conn() as c:
        g = own_group(c, uid, group_id)
        meal = pick(body["meal"], MEALS, "meal", nullable=True) if "meal" in body else g["meal"]
        amount, unit, frac = portion_body(g, body)
        k = frac / g["fraction"] if g["fraction"] else 1.0
        rows = c.execute("SELECT * FROM entries WHERE user_id=? AND group_id=? AND food_id IS NOT NULL ORDER BY id", (uid, group_id)).fetchall()
        gid = new_group(c, uid, day, meal, g["meal_id"], g["name"], amount, unit, frac, group_portions(g))
        for row in rows:
            try:
                log_entry(c, uid, need_food(c, row["food_id"]), round(row["amount"] * k, 4), row["unit"], day, meal, gid)
            except (ValueError, HTTPException):
                continue  # a food whose unit can no longer be reached is left out
        if not c.execute("SELECT 1 FROM entries WHERE group_id=?", (gid,)).fetchone():
            raise bad("Nothing in this recipe log can be logged again.")
        if meal and g["meal_id"] is not None and c.execute("SELECT 1 FROM meals WHERE id=? AND user_id=?", (g["meal_id"], uid)).fetchone():
            c.execute("INSERT OR IGNORE INTO recipe_tags(meal_id, meal) VALUES(?,?)", (g["meal_id"], meal))
            c.execute("INSERT INTO recipe_logs(meal_id, meal) VALUES(?,?)", (g["meal_id"], meal))
        return group_out(c, uid, gid)


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
    row = c.execute(f"SELECT {', '.join(DISPLAY_FLAGS)}, micros_hidden, today_view, search_source, auto_match FROM settings WHERE user_id=?",
                    (uid,)).fetchone()
    out = {k: bool(row[k]) if row else bool(v) for k, v in DISPLAY_FLAGS.items()}
    hidden = set((row["micros_hidden"] if row else "").split(","))
    out["micros_shown"] = [k for k in MICROS if k not in hidden]
    out["today_view"] = row["today_view"] if row and row["today_view"] in TODAY_VIEWS else "list"
    out["search_source"] = row["search_source"] if row and row["search_source"] in START_SOURCES else "all"
    out["auto_match"] = row["auto_match"] if row and row["auto_match"] in AUTO_MATCHES else "search"
    return out


@router.get("/settings/display")
def get_display(user: CurrentUser):
    with db.conn() as c:
        return read_display(c, user["id"])


@router.put("/settings/display")
def put_display(user: CurrentUser, body: dict = Body(...)):
    """Per user show/hide switches. Send any subset; micros_shown is the list of nutrients to show."""
    if not (set(DISPLAY_FLAGS) | {"micros_shown", "today_view", "search_source", "auto_match"}) & body.keys():
        raise bad("Nothing to update: send " + ", ".join(DISPLAY_FLAGS) + ", micros_shown, today_view, search_source or auto_match")
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
        if "today_view" in body:
            if body["today_view"] not in TODAY_VIEWS:  # also rejects non-strings and unhashable values
                raise bad("today_view must be " + " or ".join(TODAY_VIEWS))
            d["today_view"] = body["today_view"]
        if "search_source" in body:
            if body["search_source"] not in START_SOURCES:
                raise bad("search_source must be " + ", ".join(START_SOURCES))
            d["search_source"] = body["search_source"]
        if "auto_match" in body:
            if body["auto_match"] not in AUTO_MATCHES:
                raise bad("auto_match must be one of " + ", ".join(AUTO_MATCHES[:-1]) + " or " + AUTO_MATCHES[-1])
            d["auto_match"] = body["auto_match"]
        cols = [*DISPLAY_FLAGS, "micros_hidden", "today_view", "search_source", "auto_match"]
        vals = [int(d[k]) for k in DISPLAY_FLAGS] + [",".join(k for k in MICROS if k not in d["micros_shown"]), d["today_view"],
                                                     d["search_source"], d["auto_match"]]
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
        rows = c.execute("SELECT e.*, f.source AS source FROM entries e LEFT JOIN foods f ON f.id=e.food_id "
                         "WHERE e.user_id=? AND e.day=? ORDER BY e.id", (user["id"], day)).fetchall()
        goals = read_goals(c, user["id"])
        mtargets = micro_targets(c, user["id"])
        items = day_items(c, user["id"], rows)  # totals and micros below still count every ingredient row once, as before
    sums = {k: sum(r[k] or 0 for r in rows) for k in (*MACROS, "fiber")}
    targets = {"kcal": float(goals["kcal"])}
    for key, (pct, kcal_g) in GOAL_KEYS.items():
        targets[key] = goals["kcal"] * goals[pct] / 100 / kcal_g
    return {"day": day, "entries": items,
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
        amount, unit = units.default_pick(food)
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
        base_amount, base_unit = units.default_pick(food)  # the package's own serving until the food is logged
        amount = r["lu_amount"] if r["lu_amount"] is not None else base_amount
        unit = r["lu_unit"] or base_unit
        items.append(quick_item(food, amount, unit, r["last_meal"]))
    return {"items": items}


@router.get("/quick/favorites")
def quick_favorites(user: CurrentUser):
    with db.conn() as c:
        rows = c.execute(
            "SELECT f.*, lu.amount AS lu_amount, lu.unit AS lu_unit, " + LAST_MEAL.replace("lu.user_id", "v.user_id") +
            " FROM favorites v JOIN foods f ON f.id=v.food_id "
            f"LEFT JOIN last_used lu ON lu.food_id=f.id AND lu.user_id=v.user_id WHERE v.user_id=? AND {VISIBLE} "
            "ORDER BY (lu.used_at IS NULL), lu.used_at DESC, f.name", (user["id"], user["id"])).fetchall()
        out = items_from_rows(rows)
        tags, counts = favorite_tags(c, user["id"]), meal_counts(c, user["id"])
    for it in out["items"]:
        it["meals"], it["counts"] = tags.get(it["food"]["id"], []), counts.get(it["food"]["id"], {})
    return out


def logged_meals(c, uid: int) -> dict:
    """{food_id: [meals the user logged it as]} in breakfast..dessert order, from entries (null meals left out)."""
    out: dict = {}
    for r in c.execute("SELECT DISTINCT food_id, meal FROM entries WHERE user_id=? AND food_id IS NOT NULL AND meal IS NOT NULL", (uid,)):
        out.setdefault(r["food_id"], set()).add(r["meal"])
    return {k: [m for m in MEALS if m in v] for k, v in out.items()}


@router.get("/quick/recent")
def quick_recent(user: CurrentUser, meal: str | None = None):
    """Recently logged foods, newest first. With meal (breakfast..dessert) only foods the user logged as that meal, plus foods
    never logged with a meal (they show under every meal, like untagged favorites). No meal or all keeps every food.
    Items carry meals (the meals the food was logged as) and counts ({meal: times logged}), the same shape as favorites."""
    meal_sql, meal_args = "", []
    if meal not in (None, "", "all"):
        pick(meal, MEALS, "meal")
        own = "FROM entries x WHERE x.user_id=lu.user_id AND x.food_id=f.id"
        meal_sql = f"AND (EXISTS(SELECT 1 {own} AND x.meal=?) OR NOT EXISTS(SELECT 1 {own} AND x.meal IS NOT NULL)) "
        meal_args = [meal]
    with db.conn() as c:
        rows = c.execute(
            "SELECT f.*, lu.amount AS lu_amount, lu.unit AS lu_unit, " + LAST_MEAL +
            " FROM last_used lu JOIN foods f ON f.id=lu.food_id "
            f"WHERE lu.user_id=? AND f.id NOT IN (SELECT food_id FROM hidden_foods WHERE user_id=lu.user_id) AND {VISIBLE} "
            f"{meal_sql}ORDER BY lu.used_at DESC, f.id DESC LIMIT 20", (user["id"], user["id"], *meal_args)).fetchall()
        out = items_from_rows(rows)
        tags, counts = logged_meals(c, user["id"]), meal_counts(c, user["id"])
    for it in out["items"]:
        it["meals"], it["counts"] = tags.get(it["food"]["id"], []), counts.get(it["food"]["id"], {})
    return out


@router.get("/quick/yesterday")
def quick_yesterday(user: CurrentUser, day: str | None = None):
    prev = (date.fromisoformat(day_str(day)) - timedelta(days=1)).isoformat()
    with db.conn() as c:
        entries = c.execute("SELECT e.id, e.food_id, e.amount, e.unit, e.meal FROM entries e JOIN foods f ON f.id=e.food_id "
                            f"WHERE e.user_id=? AND e.day=? AND e.group_id IS NULL AND {VISIBLE} "
                            "AND e.food_id NOT IN (SELECT food_id FROM hidden_foods WHERE user_id=?) "
                            "ORDER BY e.id", (user["id"], prev, user["id"], user["id"])).fetchall()
        last: dict = {}  # last entry per distinct (food, meal) pair, in order of that last entry
        for e in entries:
            key = (e["food_id"], e["meal"])
            last.pop(key, None)
            last[key] = e
        items = [(e["id"], quick_item(need_food(c, fid), e["amount"], e["unit"], e["meal"])) for (fid, _), e in last.items()]
        # Recipe logs stay one item each (kind recipe, at their first ingredient), logged again as one group by POST /api/entry-groups/{id}/copy
        firsts = c.execute("SELECT group_id, MIN(id) AS first FROM entries WHERE user_id=? AND day=? AND group_id IS NOT NULL GROUP BY group_id",
                           (user["id"], prev)).fetchall()
        for r in firsts:
            try:
                g = group_out(c, user["id"], r["group_id"])
            except HTTPException:
                continue
            items.append((r["first"], {k: g[k] for k in ("kind", "group_id", "meal_id", "name", "amount", "unit", "fraction", "portions",
                                                          "meal", "kcal", "carbs", "protein", "fat")} | {"parts": len(g["parts"])}))
    return {"items": [it for _, it in sorted(items, key=lambda x: x[0])]}


def clean_tags(v) -> list[str]:
    """A list of meal names, de-duplicated and in breakfast..dessert order."""
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
        undelete(c, user["id"], food_id)
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


SRC_KEYS = ("text", "amount", "unit", "name", "note")


def item_dict(c, it) -> dict:
    """One recipe ingredient. Unmatched rows have food null and null nutrients; skipped rows count for nothing."""
    src = {k: it["src_" + k] for k in SRC_KEYS} if it["src_text"] is not None or it["src_name"] is not None else None
    check = it["food_id"] is not None and bool(it["needs_check"])
    base = {"id": it["id"], "food_id": it["food_id"], "amount": it["amount"], "unit": it["unit"], "src": src,
            "skipped": bool(it["skipped"]), "matched": it["food_id"] is not None and not check, "check": check}
    if it["food_id"] is None:
        return {**base, "food": None, "servings": None, "estimated": False, "grams": None, **{k: None for k in (*MACROS, *MICROS)}}
    food = need_food(c, it["food_id"])
    return {**base, "food": food, "grams": units.grams(food, it["amount"], it["unit"]), **macros(food, it["amount"], it["unit"])}


def recipe_totals(items: list) -> dict:
    """Sums over matched (amount confirmed), not skipped rows. A micronutrient is null when no counted row knows it."""
    counted = [i for i in items if i["matched"] and not i["skipped"]]
    out = {k: r2(sum(i[k] for i in counted)) for k in MACROS}
    for k in MICROS:
        known = [i[k] for i in counted if i[k] is not None]
        out[k] = r2(sum(known)) if known else None
    return out


# ---------- recipe yield and portions ----------

YIELD_UNITS = (*units.MASS, *units.VOLUME)  # a total yield is a weight or a volume
YIELD_MAX = 1_000_000
RECIPE_PCT = units.PCT  # "pct": percent of the whole recipe when logging a recipe
MAX_WHOLE_RECIPES = 100  # one log takes at most this many whole recipes


def row_yield(row) -> dict | None:
    keys = row.keys()
    if "yield_amount" not in keys or row["yield_amount"] is None or row["yield_unit"] not in YIELD_UNITS:
        return None
    return {"amount": row["yield_amount"], "unit": row["yield_unit"]}


def recipe_yield(v) -> dict | None:
    """The optional total yield of a recipe: null, or {"amount": > 0, "unit": a weight or volume unit}."""
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) - {"amount", "unit"}:
        raise bad("yield must be null or an object with amount and unit")
    amount = number(v.get("amount"), "yield amount", positive=True)
    if amount > YIELD_MAX:
        raise bad(f"yield amount must be {YIELD_MAX} or less")
    try:
        unit = units.parse_unit(v.get("unit"))
    except ValueError:
        unit = None
    if unit not in YIELD_UNITS:
        raise bad("yield unit must be a weight or volume unit: " + ", ".join(YIELD_UNITS))
    return {"amount": amount, "unit": unit}


def portions(servings: float, yld: dict | None) -> list[dict]:
    """Units a recipe can be logged in, each with whole = how many of it make the whole recipe: servings, percent of the
    recipe (always), and with a yield its unit first, then the other units of the same family (weight or volume)."""
    out = [{"unit": units.SERVING, "label": "servings", "whole": servings},
           {"unit": RECIPE_PCT, "label": "% of recipe", "whole": 100.0}]
    if yld:
        fam = units.MASS if yld["unit"] in units.MASS else units.VOLUME
        base = yld["amount"] * fam[yld["unit"]]
        for u in [yld["unit"], *[u for u in units.ORDER if u in fam and u != yld["unit"]]]:
            out.append({"unit": u, "label": units.LABELS.get(u, u), "whole": round(base / fam[u], 6)})
    return out


def recipe_fraction(meal: dict, amount, unit) -> float:
    """The share of the whole recipe that amount of unit is (servings, pct or a yield unit). Raises 400."""
    a = number(amount, "amount", positive=True)
    for p in meal["portions"]:
        if p["unit"] == unit:
            frac = a / p["whole"]
            if frac > MAX_WHOLE_RECIPES:
                raise bad(f"That is more than {MAX_WHOLE_RECIPES} times the whole recipe")
            return frac
    raise bad("unit must be one of " + ", ".join(p["unit"] for p in meal["portions"]))


def exact_grams(item: dict) -> float | None:
    """Grams of one matched row when its weight is known exactly (a weight unit, or the food's own serving_g)."""
    if item["unit"] in units.MASS:
        return round(item["amount"] * units.MASS[item["unit"]], 1)
    return item["grams"]


def ingredient_grams(items: list, complete: bool) -> float | None:
    """Total weight of a complete recipe when every counted row has an exact gram weight, else None."""
    counted = [i for i in items if i["matched"] and not i["skipped"]]
    if not complete or not counted:
        return None
    g = [exact_grams(i) for i in counted]
    return None if any(x is None for x in g) else r1(sum(g))


def meal_dict(c, row) -> dict:
    items = [item_dict(c, it) for it in c.execute("SELECT * FROM meal_items WHERE meal_id=? ORDER BY position, id", (row["id"],))]
    tags = clean_tags([r["meal"] for r in c.execute("SELECT meal FROM recipe_tags WHERE meal_id=?", (row["id"],))])
    counts = {r["meal"]: r["n"] for r in c.execute("SELECT meal, COUNT(*) n FROM recipe_logs WHERE meal_id=? GROUP BY meal", (row["id"],))}
    totals = recipe_totals(items)
    servings = row["servings"] or 1
    needed = [i for i in items if not i["skipped"]]
    matched = sum(1 for i in needed if i["matched"])
    complete = bool(needed) and matched == len(needed)
    yld = row_yield(row)
    return {"id": row["id"], "name": row["name"], "meal": tags[0] if tags else None, "meals": tags, "counts": counts,
            "items": items, "kcal": r1(totals["kcal"]), "servings": servings, "totals": totals,
            "per_serving": {k: None if v is None else r2(v / servings) for k, v in totals.items()},
            "matched": matched, "needed": len(needed), "skipped": len(items) - len(needed),
            "checks": sum(1 for i in needed if i["check"]), "steps": read_steps(row["steps"]),
            "complete": complete, "yield": yld, "portions": portions(servings, yld),
            "ingredient_grams": ingredient_grams(items, complete)}


MAX_STEPS = 60
MAX_STEP_LEN = 1000


def read_steps(raw) -> list[str]:
    """meals.steps as a list. Null, empty or unreadable means no steps."""
    try:
        v = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def clean_steps(v) -> list[str]:
    """Recipe method steps: a list of text, in order. Blank steps are dropped, whitespace inside a step is folded.
    Steps are notes only and never change nutrition or logging."""
    if v is None:
        return []
    if not isinstance(v, list):
        raise bad("steps must be a list of text")
    out = []
    for i, s in enumerate(v, 1):
        if not isinstance(s, str):
            raise bad(f"step {i} must be text")
        s = " ".join(s.split())
        if len(s) > MAX_STEP_LEN:
            raise bad(f"step {i} must be {MAX_STEP_LEN} characters or fewer")
        if s:
            out.append(s)
    if len(out) > MAX_STEPS:
        raise bad(f"A recipe can have at most {MAX_STEPS} steps")
    return out


def steps_json(steps: list[str]):
    return json.dumps(steps) if steps else None


def save_meal(c, uid: int, name, items: list, meal: str | list | None = None, steps: list | None = None) -> dict:
    """meal is one meal name, a list of meal names (the recipe tags), or None. meals.meal keeps the first tag."""
    tags = [meal] if isinstance(meal, str) else clean_tags(meal or [])
    cur = c.execute("INSERT INTO meals(user_id, name, meal, steps) VALUES(?,?,?,?)", (uid, name, tags[0] if tags else None, steps_json(steps or [])))
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
    steps = clean_steps(body.get("steps"))
    with db.conn() as c:
        return save_meal(c, user["id"], name, parse_items(c, body.get("items")), tags, steps)


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
    """Rename, retag (meals), set servings, yield or steps, or replace the items list (amounts, units, removed items)."""
    if not {"name", "meals", "items", "servings", "steps", "yield"} & body.keys():
        raise bad("Nothing to update: send name, meals, items, servings, yield or steps")
    yld = recipe_yield(body["yield"]) if "yield" in body else None
    steps = clean_steps(body["steps"]) if "steps" in body else None
    name = meal_name(body) if "name" in body else None
    tags = clean_tags(body["meals"]) if "meals" in body else None
    servings = recipe_servings(body["servings"]) if "servings" in body else None
    with db.conn() as c:
        own_meal(c, user["id"], meal_id)
        items = parse_items(c, body["items"]) if "items" in body else None
        if name:
            c.execute("UPDATE meals SET name=? WHERE id=?", (name, meal_id))
        if "servings" in body:
            c.execute("UPDATE meals SET servings=? WHERE id=?", (servings, meal_id))
        if "yield" in body:
            c.execute("UPDATE meals SET yield_amount=?, yield_unit=? WHERE id=?",
                      (yld and yld["amount"], yld and yld["unit"], meal_id))
        if steps is not None:  # allowed at any time, also while ingredients are still being matched
            c.execute("UPDATE meals SET steps=? WHERE id=?", (steps_json(steps), meal_id))
        if tags is not None:
            c.execute("DELETE FROM recipe_tags WHERE meal_id=?", (meal_id,))
            c.executemany("INSERT INTO recipe_tags(meal_id, meal) VALUES(?,?)", [(meal_id, m) for m in tags])
        if items is not None:
            # Only the counted rows are replaced. Unmatched, skipped and Check Amount rows stay as reference lines after them.
            c.execute("DELETE FROM meal_items WHERE meal_id=? AND food_id IS NOT NULL AND skipped=0 AND needs_check=0", (meal_id,))
            c.execute("UPDATE meal_items SET position=position+? WHERE meal_id=?", (len(items), meal_id))
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


def need_matched(c, row) -> None:
    """Matching is optional: a recipe logs with any mix of matched, skipped and unmatched rows. The one refusal is a recipe
    with nothing matched, which would log nothing."""
    if not c.execute("SELECT 1 FROM meal_items WHERE meal_id=? AND food_id IS NOT NULL AND skipped=0 AND needs_check=0", (row["id"],)).fetchone():
        raise bad("Match at least one ingredient to log this recipe.")


def recipe_servings(v):
    """Servings the whole recipe makes: null (one), or a number above 0 and at most 1000."""
    if v is None:
        return None
    x = number(v, "servings", positive=True)
    if x > 1000:
        raise bad("servings must be 1000 or fewer")
    return x


def short_text(v, name: str, limit: int, required: bool = False):
    if v is None or (isinstance(v, str) and not v.strip() and not required):
        if required:
            raise bad(f"{name} is required")
        return None
    if not isinstance(v, str):
        raise bad(f"{name} must be text")
    v = " ".join(v.split())
    if required and not v:
        raise bad(f"{name} is required")
    if len(v) > limit:
        raise bad(f"{name} must be {limit} characters or fewer")
    return v


MAX_IMPORT_ROWS = 100


def import_row(raw) -> tuple:
    """(text, amount, unit, name, note) of one imported ingredient line, validated."""
    if not isinstance(raw, dict) or set(raw) - set(SRC_KEYS):
        raise bad("must be an object with text, amount, unit, name and note")
    name = short_text(raw.get("name"), "name", 200, required=True)
    amount = number(raw.get("amount"), "amount", optional=True)
    unit = short_text(raw.get("unit"), "unit", 40)
    note = short_text(raw.get("note"), "note", 300)
    text = short_text(raw.get("text"), "text", 300) or " ".join(str(x) for x in (
        None if amount is None else f"{amount:g}", unit, name) if x) + (f", {note}" if note else "")
    return text, amount, unit, name, note


@router.post("/meals/import")
def import_meal(user: CurrentUser, body: dict = Body(...)):
    """Save an imported recipe at once with every ingredient unmatched. Matching happens afterwards, row by row."""
    name = meal_name(body)
    if len(name) > 200:
        raise bad("name must be 200 characters or fewer")
    tags = clean_tags(body.get("meals") or [])
    servings = recipe_servings(body.get("servings"))
    raw = body.get("ingredients")
    if not isinstance(raw, list) or not raw:
        raise bad("ingredients must be a non-empty list")
    if len(raw) > MAX_IMPORT_ROWS:
        raise bad(f"A recipe can have at most {MAX_IMPORT_ROWS} ingredients")
    steps = clean_steps(body.get("steps"))
    rows = []
    for i, it in enumerate(raw, 1):
        try:
            rows.append(import_row(it))
        except HTTPException as e:
            raise HTTPException(400, f"ingredient {i}: {e.detail}")
    with db.conn() as c:
        cur = c.execute("INSERT INTO meals(user_id, name, meal, servings, steps) VALUES(?,?,?,?,?)",
                        (user["id"], name, tags[0] if tags else None, servings, steps_json(steps)))
        c.executemany("INSERT INTO recipe_tags(meal_id, meal) VALUES(?,?)", [(cur.lastrowid, m) for m in tags])
        c.executemany("INSERT INTO meal_items(meal_id, position, src_text, src_amount, src_unit, src_name, src_note) VALUES(?,?,?,?,?,?,?)",
                      [(cur.lastrowid, i, *r) for i, r in enumerate(rows)])
        return meal_dict(c, own_meal(c, user["id"], cur.lastrowid))


@router.get("/meals/{meal_id}")
def get_meal(meal_id: int, user: CurrentUser):
    with db.conn() as c:
        return meal_dict(c, own_meal(c, user["id"], meal_id))


def own_item(c, meal_id: int, item_id: int):
    row = c.execute("SELECT * FROM meal_items WHERE id=? AND meal_id=?", (item_id, meal_id)).fetchone()
    if not row:
        raise HTTPException(404, "Ingredient not found")
    return row


ITEM_KEYS = {"food_id", "amount", "unit", "skipped", "check"}


def check_item_body(body) -> None:
    if not isinstance(body, dict) or not body or set(body) - ITEM_KEYS:
        raise bad("Send food_id with amount and unit, food_id null, or skipped")
    if "skipped" in body and not isinstance(body["skipped"], bool):
        raise bad("skipped must be true or false")
    if "check" in body and (not isinstance(body["check"], bool) or body.get("food_id") is None):
        raise bad("check must be true or false and needs food_id")
    if "food_id" not in body and {"amount", "unit"} & body.keys():
        raise bad("Send food_id together with amount and unit")


def apply_item(c, item_id: int, body: dict, uid: int | None = None) -> None:
    """Match ({food_id, amount, unit, check?}), unmatch ({food_id: null}) and or skip ({skipped}) one checked row.
    A match clears skipped unless skipped is sent too; skipped is applied last."""
    if "food_id" in body and body["food_id"] is None:
        row = c.execute("SELECT mi.src_text, mi.src_name, mi.amount, mi.unit, f.name FROM meal_items mi LEFT JOIN foods f ON f.id=mi.food_id "
                        "WHERE mi.id=?", (item_id,)).fetchone()
        if row and row["src_text"] is None and row["src_name"] is None and row["name"]:
            # A row of a recipe built by hand has no imported line. Unmatching must not leave a row with no name, so the food's
            # name and amount become its line, and the row can be searched again on Match Ingredients.
            c.execute("UPDATE meal_items SET src_text=?, src_name=?, src_amount=?, src_unit=? WHERE id=?",
                      (row["name"][:300], row["name"][:200], row["amount"], row["unit"], item_id))
        c.execute("UPDATE meal_items SET food_id=NULL, amount=NULL, unit=NULL, needs_check=0 WHERE id=?", (item_id,))
    elif "food_id" in body:
        food = need_food(c, whole_id(body["food_id"], "food_id"))
        amount, unit = check_amount_unit(food, body.get("amount"), body.get("unit"))
        c.execute("UPDATE meal_items SET food_id=?, amount=?, unit=?, skipped=0, needs_check=? WHERE id=?",
                  (food["id"], amount, unit, int(body.get("check") is True), item_id))
        if uid is not None:
            undelete(c, uid, food["id"])  # picking a deleted food again for a recipe brings it back
    if "skipped" in body:
        c.execute("UPDATE meal_items SET skipped=? WHERE id=?", (int(body["skipped"]), item_id))


@router.patch("/meals/{meal_id}/items/{item_id}")
def patch_meal_item(meal_id: int, item_id: int, user: CurrentUser, body: dict = Body(...)):
    """Match one ingredient ({food_id, amount, unit, check?}), unmatch it ({food_id: null}), or skip it ({skipped: bool}).
    check true attaches the food with an amount still to confirm (Check Amount); a match without check confirms it."""
    check_item_body(body)
    with db.conn() as c:
        own_meal(c, user["id"], meal_id)
        own_item(c, meal_id, item_id)
        apply_item(c, item_id, body, user["id"])
        return meal_dict(c, own_meal(c, user["id"], meal_id))


@router.patch("/meals/{meal_id}/items")
def patch_meal_items(meal_id: int, user: CurrentUser, body: dict = Body(...)):
    """Several rows at once, all or nothing: {"items": [{"id", ...same body as one row}]} (1..100 rows, each id once).
    Used by Accept All, Skip All and Back on Match Ingredients (which writes the last saved state back)."""
    raw = body.get("items") if isinstance(body, dict) else None
    if not isinstance(raw, list) or not raw or len(raw) > MAX_IMPORT_ROWS:
        raise bad(f"items must be a list of 1 to {MAX_IMPORT_ROWS} rows")
    changes = []
    for i, it in enumerate(raw, 1):
        try:
            if not isinstance(it, dict):
                raise bad("must be an object with id")
            rest = {k: v for k, v in it.items() if k != "id"}
            check_item_body(rest)
            changes.append((whole_id(it.get("id"), "id"), rest))
        except HTTPException as e:
            raise HTTPException(e.status_code, f"row {i}: {e.detail}")
    if len({x[0] for x in changes}) != len(changes):
        raise bad("Each row may appear only once")
    with db.conn() as c:
        own_meal(c, user["id"], meal_id)
        for item_id, _ in changes:
            own_item(c, meal_id, item_id)
        for i, (item_id, rest) in enumerate(changes, 1):  # db.conn commits only when every row went through
            try:
                apply_item(c, item_id, rest, user["id"])
            except HTTPException as e:
                raise HTTPException(e.status_code, f"row {i}: {e.detail}")
        return meal_dict(c, own_meal(c, user["id"], meal_id))


ADD_KEYS = {"src", "food_id", "amount", "unit", "check", "skipped", "position"}


@router.post("/meals/{meal_id}/items")
def add_meal_item(meal_id: int, user: CurrentUser, body: dict = Body(...)):
    """Add one ingredient row to my recipe (Match Ingredients). {"src": {text?, amount?, unit?, name, note?}} adds an unmatched line;
    "food_id" with "amount" and "unit" (and "check"?) attaches a food; both may be sent (Back on Match Ingredients puts a removed
    row back this way, with "skipped" and "position", the 0 based place in the list). The row goes last without a position.
    Answers the recipe plus "added", the new row's id."""
    if not body or set(body) - ADD_KEYS or ("src" not in body and "food_id" not in body):
        raise bad("Send src (the ingredient line) and or food_id with amount and unit")
    if "skipped" in body and not isinstance(body["skipped"], bool):
        raise bad("skipped must be true or false")
    if "check" in body and (not isinstance(body["check"], bool) or body.get("food_id") is None):
        raise bad("check must be true or false and needs food_id")
    if "food_id" not in body and {"amount", "unit"} & body.keys():
        raise bad("Send food_id together with amount and unit")
    src = import_row(body["src"]) if "src" in body else (None,) * 5
    pos = body.get("position")
    if pos is not None and (isinstance(pos, bool) or not isinstance(pos, int) or pos < 0):
        raise bad("position must be a whole number of 0 or more")
    with db.conn() as c:
        row = own_meal(c, user["id"], meal_id)
        ids = [r["id"] for r in c.execute("SELECT id FROM meal_items WHERE meal_id=? ORDER BY position, id", (meal_id,))]
        if len(ids) >= MAX_IMPORT_ROWS:
            raise HTTPException(409, f"A recipe can have at most {MAX_IMPORT_ROWS} ingredients")
        food_id = amount = unit = None
        if body.get("food_id") is not None:
            food = need_food(c, whole_id(body["food_id"], "food_id"))
            amount, unit = check_amount_unit(food, body.get("amount"), body.get("unit"))
            food_id = food["id"]
            undelete(c, user["id"], food_id)
        cur = c.execute("INSERT INTO meal_items(meal_id, food_id, amount, unit, position, src_text, src_amount, src_unit, src_name, src_note,"
                        " skipped, needs_check) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (meal_id, food_id, amount, unit, len(ids), *src, int(body.get("skipped") is True), int(body.get("check") is True)))
        ids.insert(len(ids) if pos is None else min(pos, len(ids)), cur.lastrowid)
        c.executemany("UPDATE meal_items SET position=? WHERE id=?", [(i, x) for i, x in enumerate(ids)])
        return {**meal_dict(c, row), "added": cur.lastrowid}


@router.delete("/meals/{meal_id}/items/{item_id}")
def delete_meal_item(meal_id: int, item_id: int, user: CurrentUser):
    """Remove one ingredient row from my recipe. The last row cannot be removed (delete the recipe instead)."""
    with db.conn() as c:
        row = own_meal(c, user["id"], meal_id)
        own_item(c, meal_id, item_id)
        if c.execute("SELECT COUNT(*) FROM meal_items WHERE meal_id=?", (meal_id,)).fetchone()[0] <= 1:
            raise HTTPException(409, "A recipe needs at least one ingredient. Delete the recipe instead.")
        c.execute("DELETE FROM meal_items WHERE id=?", (item_id,))
        return meal_dict(c, row)


@router.delete("/meals/{meal_id}/uncounted")
def delete_uncounted_items(meal_id: int, user: CurrentUser):
    """Save Without Them on Match Ingredients: remove every row that counts for nothing (unmatched, skipped, Check Amount).
    Nothing is kept for them, no text line either. At least one matched row must be left."""
    with db.conn() as c:
        row = own_meal(c, user["id"], meal_id)
        if not c.execute("SELECT 1 FROM meal_items WHERE meal_id=? AND food_id IS NOT NULL AND skipped=0 AND needs_check=0", (meal_id,)).fetchone():
            raise bad("A recipe needs at least one ingredient. Match one, or keep the others to finish later.")
        c.execute("DELETE FROM meal_items WHERE meal_id=? AND NOT (food_id IS NOT NULL AND skipped=0 AND needs_check=0)", (meal_id,))
        return meal_dict(c, row)


@router.post("/meals/{meal_id}/log")
def log_meal(meal_id: int, user: CurrentUser, body: dict | None = Body(None)):
    body = body or {}
    day, meal = day_str(body.get("day")), pick(body.get("meal"), MEALS, "meal", nullable=True)
    with db.conn() as c:
        row = own_meal(c, user["id"], meal_id)
        need_matched(c, row)
        md = meal_dict(c, row)
        # amount and unit: how much of the recipe (servings, pct of the recipe, or a yield unit), as a share of the whole.
        # With items (the checklist) they only name the portion of the recipe log; without either it is the whole recipe.
        given = "amount" in body or "unit" in body
        frac = recipe_fraction(md, body.get("amount"), body.get("unit")) if given else None
        if body.get("items") is not None:  # the client's checklist replaces the saved items
            items = parse_items(c, body["items"])
        else:
            items = [(need_food(c, i["food_id"]), i["amount"] if frac is None else round(i["amount"] * frac, 4), i["unit"]) for i in
                     c.execute("SELECT * FROM meal_items WHERE meal_id=? AND food_id IS NOT NULL AND skipped=0 AND needs_check=0 "
                                 "ORDER BY position, id", (row["id"],))]
        if meal:  # logging a recipe with a meal tags the recipe and counts toward that meal
            c.execute("INSERT OR IGNORE INTO recipe_tags(meal_id, meal) VALUES(?,?)", (meal_id, meal))
            c.execute("INSERT INTO recipe_logs(meal_id, meal) VALUES(?,?)", (meal_id, meal))
        amount, unit = (float(body["amount"]), body["unit"]) if given else (md["servings"], units.SERVING)
        gid = new_group(c, user["id"], day, meal, meal_id, row["name"], amount, unit, 1.0 if frac is None else frac, md["portions"])
        entries = [log_entry(c, user["id"], f, a, u, day, meal, gid) for f, a, u in items]
        return {"entries": entries, "group": group_out(c, user["id"], gid)}


# ---------- saved screen: favorites, recipes and my foods ----------

NUTRITION = ("serving_amount", "serving_unit", "serving_g", "serving_ml", "kcal", "carbs", "protein", "fat", *MICROS)
FOOD_EDITABLE = ("name", "brand", "barcode", "label_text", *NUTRITION)
IN_USE = "(EXISTS(SELECT 1 FROM entries WHERE food_id=f.id) OR EXISTS(SELECT 1 FROM meal_items WHERE food_id=f.id))"


@router.get("/saved")
def get_saved(user: CurrentUser):
    uid = user["id"]
    with db.conn() as c:
        tags = favorite_tags(c, uid)
        favs = c.execute(f"SELECT f.* FROM favorites v JOIN foods f ON f.id=v.food_id WHERE v.user_id=? AND {VISIBLE} "
                         "ORDER BY f.name COLLATE NOCASE, f.id", (uid, uid)).fetchall()
        recipes = c.execute("SELECT * FROM meals WHERE user_id=? ORDER BY name COLLATE NOCASE, id", (uid,)).fetchall()
        mine = c.execute(f"SELECT f.*, {IN_USE} AS in_use FROM foods f WHERE f.created_by=? AND f.source IN ('custom','ai') AND {VISIBLE} "
                         "ORDER BY f.name COLLATE NOCASE, f.id", (uid, uid)).fetchall()
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
    """Soft delete. The food leaves my lists, search, favorites, picker and Saved, but nothing is removed: log entries and recipe
    rows keep it, so history and totals never change. A shared Open Food Facts or USDA food, or anyone else's food, is only hidden
    for me. A custom or Claude food I created is hidden for everyone, but only when no other user has it in favorites, entries or
    recipes; otherwise it is hidden for me alone. Logging, favoriting or scanning it again brings it back."""
    uid = user["id"]
    with db.conn() as c:
        row = c.execute("SELECT id, source, created_by FROM foods WHERE id=?", (food_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Food not found")
        for table in ("favorites", "favorite_tags", "hidden_foods"):
            c.execute(f"DELETE FROM {table} WHERE user_id=? AND food_id=?", (uid, food_id))
        c.execute("INSERT OR IGNORE INTO deleted_foods(user_id, food_id) VALUES(?,?)", (uid, food_id))
        everyone = False
        if row["source"] in ("custom", "ai") and row["created_by"] == uid:
            others = c.execute("SELECT 1 FROM favorites WHERE food_id=? AND user_id<>? UNION ALL "
                               "SELECT 1 FROM entries WHERE food_id=? AND user_id<>? UNION ALL "
                               "SELECT 1 FROM meal_items mi JOIN meals m ON m.id=mi.meal_id WHERE mi.food_id=? AND m.user_id<>? LIMIT 1",
                               (food_id, uid, food_id, uid, food_id, uid)).fetchone()
            if not others:
                c.execute("UPDATE foods SET deleted=1 WHERE id=?", (food_id,))
                everyone = True
    return {"deleted": food_id, "everyone": everyone}
