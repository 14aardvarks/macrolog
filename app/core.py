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
FOOD_COLS = ("id", "source", "source_id", "barcode", "name", "brand", "serving_amount", "serving_unit",
             "serving_g", "serving_ml", "label_text", "kcal", "carbs", "protein", "fat", "fiber")
ENTRY_COLS = ("id", "day", "meal", "food_id", "name", "brand", "amount", "unit", "servings",
              "kcal", "carbs", "protein", "fat", "fiber")
DEFAULT_GOALS = {"kcal": 3000, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20}
GOAL_KEYS = {"carbs": ("carb_pct", 4), "protein": ("protein_pct", 4), "fat": ("fat_pct", 9)}  # pct key, kcal per g

SCHEMA = """
CREATE TABLE IF NOT EXISTS foods(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT,
  name TEXT NOT NULL, brand TEXT, serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL,
  serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',
  kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, source_id));
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
CREATE TABLE IF NOT EXISTS goals(
  user_id INTEGER PRIMARY KEY REFERENCES users(id), kcal REAL NOT NULL,
  carb_pct REAL NOT NULL, protein_pct REAL NOT NULL, fat_pct REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings(
  user_id INTEGER PRIMARY KEY REFERENCES users(id), start_screen TEXT NOT NULL DEFAULT 'today',
  default_meal TEXT, use_last INTEGER NOT NULL DEFAULT 1,
  confirm_ai INTEGER NOT NULL DEFAULT 1, amount_format TEXT NOT NULL DEFAULT 'fraction');
"""


def init(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)
    if "meal" not in {r[1] for r in c.execute("PRAGMA table_info(meals)")}:  # databases made before recipes had a meal
        c.execute("ALTER TABLE meals ADD COLUMN meal TEXT")
    if "use_last" not in {r[1] for r in c.execute("PRAGMA table_info(settings)")}:  # databases made before use_last
        c.execute("ALTER TABLE settings ADD COLUMN use_last INTEGER NOT NULL DEFAULT 1")
    cols = {r[1] for r in c.execute("PRAGMA table_info(settings)")}
    if "confirm_ai" not in cols:  # databases made before the Claude cost notice
        c.execute("ALTER TABLE settings ADD COLUMN confirm_ai INTEGER NOT NULL DEFAULT 1")
    if "amount_format" not in cols:  # databases made before fractions or decimals
        c.execute("ALTER TABLE settings ADD COLUMN amount_format TEXT NOT NULL DEFAULT 'fraction'")


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
            "label_text": " ".join(str(raw.get("label_text") or "").split()) or f"{amount:g} {unit}",
            "fiber": number(raw.get("fiber"), "fiber", optional=True)}
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
    for key in (*MACROS, "fiber"):
        out[key] = None if s[key] is None else r2(s[key])
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
        return save_food(c, food)


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
    cur = c.execute(
        "INSERT INTO entries(user_id,day,meal,food_id,name,brand,amount,unit,servings,kcal,carbs,protein,fat,fiber) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, day, meal, food["id"], food["name"], food["brand"], amount, unit, m["servings"],
         m["kcal"], m["carbs"], m["protein"], m["fat"], m["fiber"]))
    c.execute("INSERT INTO last_used(user_id,food_id,amount,unit,used_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(user_id,food_id) DO UPDATE SET amount=excluded.amount, unit=excluded.unit, "
              "used_at=excluded.used_at", (uid, food["id"], amount, unit, now()))
    return entry_dict(c.execute("SELECT * FROM entries WHERE id=?", (cur.lastrowid,)).fetchone())


@router.post("/entries")
def add_entry(user: CurrentUser, body: dict = Body(...)):
    day, meal = day_str(body.get("day")), pick(body.get("meal"), MEALS, "meal", nullable=True)
    food_id = whole_id(body.get("food_id"), "food_id")
    with db.conn() as c:
        food = need_food(c, food_id)
        amount, unit = check_amount_unit(food, body.get("amount"), body.get("unit"))
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


@router.get("/day")
def get_day(user: CurrentUser, day: str | None = None):
    day = day_str(day)
    with db.conn() as c:
        rows = c.execute("SELECT * FROM entries WHERE user_id=? AND day=? ORDER BY id", (user["id"], day)).fetchall()
        goals = read_goals(c, user["id"])
    sums = {k: sum(r[k] or 0 for r in rows) for k in (*MACROS, "fiber")}
    targets = {"kcal": float(goals["kcal"])}
    for key, (pct, kcal_g) in GOAL_KEYS.items():
        targets[key] = goals["kcal"] * goals[pct] / 100 / kcal_g
    return {"day": day, "entries": [entry_dict(r) for r in rows],
            "totals": {k: r1(v) for k, v in sums.items()},
            "targets": {k: r1(v) for k, v in targets.items()},
            "percent": {k: math.floor(100 * sums[k] / targets[k] + 0.5) if targets[k] else 0 for k in MACROS},
            "remaining": {k: r1(targets[k] - sums[k]) for k in MACROS}}


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
    return items_from_rows(rows)


@router.get("/quick/recent")
def quick_recent(user: CurrentUser):
    with db.conn() as c:
        rows = c.execute(
            "SELECT f.*, lu.amount AS lu_amount, lu.unit AS lu_unit, " + LAST_MEAL +
            " FROM last_used lu JOIN foods f ON f.id=lu.food_id "
            "WHERE lu.user_id=? ORDER BY lu.used_at DESC, f.id DESC LIMIT 20", (user["id"],)).fetchall()
    return items_from_rows(rows)


@router.get("/quick/yesterday")
def quick_yesterday(user: CurrentUser, day: str | None = None):
    prev = (date.fromisoformat(day_str(day)) - timedelta(days=1)).isoformat()
    with db.conn() as c:
        entries = c.execute("SELECT food_id, amount, unit, meal FROM entries WHERE user_id=? AND day=? "
                            "AND food_id IS NOT NULL ORDER BY id", (user["id"], prev)).fetchall()
        last: dict = {}  # last entry per distinct (food, meal) pair, in order of that last entry
        for e in entries:
            key = (e["food_id"], e["meal"])
            last.pop(key, None)
            last[key] = e
        items = [quick_item(need_food(c, fid), e["amount"], e["unit"], e["meal"]) for (fid, _), e in last.items()]
    return {"items": items}


@router.post("/favorites/{food_id}")
def add_favorite(food_id: int, user: CurrentUser):
    with db.conn() as c:
        need_food(c, food_id)
        c.execute("INSERT OR IGNORE INTO favorites(user_id, food_id) VALUES(?,?)", (user["id"], food_id))
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
    meal = row["meal"]
    return {"id": row["id"], "name": row["name"], "meal": meal, "meals": [meal] if meal else [], "items": items, "kcal": r1(sum(i["kcal"] for i in items))}


def save_meal(c, uid: int, name, items: list, meal: str | None = None) -> dict:
    cur = c.execute("INSERT INTO meals(user_id, name, meal) VALUES(?,?,?)", (uid, name, meal))
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
    name, meal = meal_name(body), pick(body.get("meal"), MEALS, "meal", nullable=True)
    with db.conn() as c:
        return save_meal(c, user["id"], name, parse_items(c, body.get("items")), meal)


@router.post("/meals/from-day")
def meal_from_day(user: CurrentUser, body: dict = Body(...)):
    name, day = meal_name(body), day_str(body.get("day"))
    wanted = body.get("entry_ids")
    if wanted is not None and not isinstance(wanted, list):
        raise bad("entry_ids must be a list")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM entries WHERE user_id=? AND day=? AND food_id IS NOT NULL ORDER BY id",
                         (user["id"], day)).fetchall()
        if wanted is not None:
            ids = {whole_id(i, "entry_ids") for i in wanted}
            if ids - {r["id"] for r in rows}:
                raise bad("Some entry_ids are not entries of yours on that day")
            rows = [r for r in rows if r["id"] in ids]
        if not rows:
            raise bad("No entries to copy for that day")
        items = [(need_food(c, r["food_id"]), r["amount"], r["unit"]) for r in rows]
        shared = {r["meal"] for r in rows}  # one meal for the whole recipe only when every entry agrees
        return save_meal(c, user["id"], name, items, shared.pop() if len(shared) == 1 else None)


@router.delete("/meals/{meal_id}")
def delete_meal(meal_id: int, user: CurrentUser):
    with db.conn() as c:
        own_meal(c, user["id"], meal_id)
        c.execute("DELETE FROM meal_items WHERE meal_id=?", (meal_id,))
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
        return {"entries": [log_entry(c, user["id"], f, a, u, day, meal) for f, a, u in items]}
