"""Micronutrients and Display settings: schema migration, lookups from saved fixtures, the AI tool schema,
the day totals, per user targets and display switches."""
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app import ai, core, lookup
from test_core import BREAD, TODAY, a, b, env, food  # noqa: F401  (fixtures)

FIX = Path(__file__).parent / "fixtures"
OFF = json.loads((FIX / "off_micros.json").read_text())
FDC = json.loads((FIX / "fdc_micros.json").read_text())


def mock(monkeypatch, off=None, fdc=None):
    def handler(request):
        if request.url.host == "world.openfoodfacts.org":
            return httpx.Response(200 if off else 404, json=off or {"status": 0})
        return httpx.Response(200, json=fdc or {"foods": []})
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(handler))


# ---------- lookups ----------

async def test_off_micros_scaled_converted_and_sodium_from_salt(monkeypatch):
    mock(monkeypatch, off=OFF)
    f = (await lookup.barcode("3017620422003"))["food"]
    assert f["fiber"] == pytest.approx(0.6) and f["sugars"] == pytest.approx(8.445, abs=0.01)
    assert f["saturated_fat"] == pytest.approx(1.59)
    assert f["sodium"] == pytest.approx(6.42, abs=0.01)  # salt 0.107 g/100 g, 15 g, / 2.5, in mg
    assert f["calcium"] == pytest.approx(16.2) and f["iron"] == pytest.approx(0.63)
    assert f["vitamin_d"] == pytest.approx(0.375, abs=0.01)  # g to mcg
    assert f["potassium"] == 60  # *_serving wins, g to mg
    assert f["cholesterol"] is None  # missing stays unknown, never 0


def test_off_sodium_wins_over_salt():
    p = {"serving_size": "100 g", "nutriments": {"energy-kcal_100g": 10, "sodium_100g": 0.2, "salt_100g": 9}}
    assert lookup.off_food("1", p)["sodium"] == 200


async def test_fdc_micros_by_nutrient_id_per_serving(monkeypatch):
    mock(monkeypatch, fdc=FDC)
    soup, rice = await lookup.search("soup")
    assert soup["kcal"] == pytest.approx(100.45) and soup["fiber"] == pytest.approx(1.96)
    assert soup["sugars"] == pytest.approx(12.005, abs=0.01) and soup["saturated_fat"] == pytest.approx(0.245, abs=0.01)
    assert (soup["sodium"], soup["potassium"], soup["calcium"]) == (pytest.approx(710.5), 490, pytest.approx(39.2))
    assert soup["iron"] == pytest.approx(1.45, abs=0.01) and soup["vitamin_d"] == pytest.approx(0.98)
    assert soup["cholesterol"] is None
    assert rice["sodium"] == 5 and rice["fiber"] == 0.4  # labelNutrients (per label serving) win
    assert rice["calcium"] is None and rice["vitamin_d"] is None


def test_convert_units():
    assert lookup.convert(1, "g", "mg") == 1000 and lookup.convert(2, "UG", "mcg") == 2
    assert lookup.convert(5, "IU", "mcg") is None and lookup.convert(None, "g", "mg") is None


# ---------- AI tool ----------

def test_ai_tool_schema_stays_within_strict_limits():
    props = ai.TOOL["input_schema"]["properties"]
    required = set(ai.TOOL["input_schema"]["required"])
    unions = [k for k, v in props.items() if isinstance(v.get("type"), list)]
    optional = [k for k in props if k not in required]
    assert len(unions) <= 16 and len(optional) <= 24
    assert set(optional) == set(core.NEW_MICROS)
    assert all(props[k]["type"] == "number" for k in optional)


def test_ai_draft_carries_micros_and_checks_them():
    data = {"name": "Soup", "serving_text": "1 cup (245 g)", "kcal": 100, "carbs": 20, "protein": 2, "fat": 1,
            "fiber": 2, "sodium": 710, "iron": 900}
    draft, warnings = ai.build_draft(data, None)
    assert draft["sodium"] == 710 and draft["sugars"] is None and draft["vitamin_d"] is None
    assert any("iron of 900" in w for w in warnings)
    assert not any("sugars" in w for w in warnings)  # optional fields left out are not reported as missing


# ---------- foods, entries, day ----------

SOUP = {"name": "Soup", "serving_amount": 1, "serving_unit": "cup", "serving_g": 245, "kcal": 100, "carbs": 20,
        "protein": 2, "fat": 1, "sodium": 700, "vitamin_d": 1.5, "sugars": 0}


def test_food_micros_stored_validated_and_scaled(a):
    f = food(a, SOUP)
    assert (f["sodium"], f["sugars"], f["cholesterol"]) == (700, 0, None)
    assert a.post("/api/foods", json=SOUP | {"sodium": -1, "source": "custom"}).status_code == 400
    p = a.get("/api/preview", params={"food_id": f["id"], "amount": 0.5, "unit": "cup"}).json()
    assert (p["sodium"], p["vitamin_d"], p["sugars"], p["iron"]) == (350, 0.75, 0, None)
    est = a.get("/api/preview", params={"food_id": f["id"], "amount": 122.5, "unit": "g"}).json()
    assert est["sodium"] == 350


def test_entries_snapshot_micros_and_day_counts_only_known(a, b):
    soup, bread = food(a, SOUP), food(a, BREAD)
    e = a.post("/api/entries", json={"food_id": soup["id"], "amount": 2, "unit": "cup", "day": TODAY}).json()
    assert e["sodium"] == 1400 and e["iron"] is None
    a.post("/api/entries", json={"food_id": bread["id"], "amount": 1, "unit": "slice", "day": TODAY})
    m = a.get("/api/day", params={"day": TODAY}).json()["micros"]
    assert m["sodium"] == {"total": 1400, "known": 1, "count": 2, "target": 2300, "kind": "limit", "unit": "mg", "percent": 61}
    assert m["fiber"]["total"] == 3 and m["fiber"]["known"] == 1 and m["fiber"]["kind"] == "goal"
    assert m["iron"]["total"] is None and m["iron"]["known"] == 0
    assert m["sugars"]["total"] == 0 and m["sugars"]["known"] == 1  # a real zero is not unknown
    assert b.get("/api/day", params={"day": TODAY}).json()["micros"]["sodium"]["count"] == 0


def test_food_edit_adds_micros_until_in_use(a):
    f = food(a, SOUP)
    assert a.patch(f"/api/foods/{f['id']}", json={"iron": 2}).json()["iron"] == 2
    a.post("/api/entries", json={"food_id": f["id"], "amount": 1, "unit": "cup"})
    assert a.patch(f"/api/foods/{f['id']}", json={"iron": 3}).status_code == 409


def test_migration_adds_micro_columns_and_display_settings(tmp_path):
    c = sqlite3.connect(tmp_path / "old.db")
    c.row_factory = sqlite3.Row
    c.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY);"
        "CREATE TABLE foods(id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT, barcode TEXT, name TEXT NOT NULL, brand TEXT,"
        " serving_amount REAL NOT NULL, serving_unit TEXT NOT NULL, serving_g REAL, serving_ml REAL, label_text TEXT NOT NULL DEFAULT '',"
        " kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL, created_at TEXT, UNIQUE(source, source_id));"
        "CREATE TABLE entries(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, meal TEXT, food_id INTEGER, name TEXT NOT NULL,"
        " brand TEXT, amount REAL NOT NULL, unit TEXT NOT NULL, servings REAL NOT NULL, kcal REAL NOT NULL, carbs REAL NOT NULL,"
        " protein REAL NOT NULL, fat REAL NOT NULL, fiber REAL, created_at TEXT);"
        "CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT);"
        "INSERT INTO settings(user_id, start_screen) VALUES(1, 'scan');"
        "INSERT INTO entries(user_id,day,name,amount,unit,servings,kcal,carbs,protein,fat,fiber) VALUES(1,'2025-01-01','Old',1,'g',1,1,1,1,1,2);")
    core.init(c)
    core.init(c)  # running twice is harmless
    row = c.execute("SELECT * FROM entries").fetchone()
    assert row["fiber"] == 2 and all(row[k] is None for k in core.NEW_MICROS)
    assert set(core.NEW_MICROS) <= {r[1] for r in c.execute("PRAGMA table_info(foods)")}
    assert core.read_display(c, 1) == {**{k: bool(v) for k, v in core.DISPLAY_FLAGS.items()}, "micros_shown": list(core.MICROS),
                                            "today_view": "list", "search_source": "all",
                                            "auto_match": "search", "recipe_owner": "mine"}
    assert c.execute("SELECT start_screen FROM settings").fetchone()[0] == "scan"


# ---------- display settings ----------

def test_display_defaults_keep_screens_as_before(a):
    d = a.get("/api/settings/display").json()
    assert d == {"show_macros": True, "show_micros": True, "show_split": True, "show_macro_bar": True, "show_table": True,
                 "group_recipes": True, "micros_open": False, "micros_shown": list(core.MICROS), "today_view": "list",
                 "search_source": "all", "auto_match": "search", "recipe_owner": "mine"}


def test_display_put_partial_per_user_and_other_settings_kept(a, b):
    a.put("/api/settings", json={"start_screen": "scan"})
    r = a.put("/api/settings/display", json={"show_split": False, "micros_open": True, "micros_shown": ["iron", "sodium", "iron"]})
    assert r.status_code == 200
    d = a.get("/api/settings/display").json()
    assert d["show_split"] is False and d["micros_open"] is True and d["micros_shown"] == ["sodium", "iron"]
    assert d["show_macros"] is True
    assert a.get("/api/settings").json()["start_screen"] == "scan"
    a.put("/api/settings", json={"use_last": False})  # saving the other settings keeps the display ones
    assert a.get("/api/settings/display").json()["show_split"] is False
    assert b.get("/api/settings/display").json()["show_split"] is True
    assert a.put("/api/settings/display", json={"micros_shown": []}).json()["micros_shown"] == []


@pytest.mark.parametrize("body", [{}, {"show_split": "no"}, {"micros_open": 1}, {"micros_shown": "iron"},
                                  {"micros_shown": ["zinc"]}, {"show_macros": None}])
def test_display_validation(a, body):
    assert a.put("/api/settings/display", json=body).status_code == 400
    assert a.get("/api/settings/display").json()["show_macros"] is True


def test_today_view_default_save_isolation_and_kept(a, b):
    assert a.put("/api/settings/display", json={"today_view": "table"}).json()["today_view"] == "table"
    assert a.get("/api/settings/display").json()["today_view"] == "table"
    assert b.get("/api/settings/display").json()["today_view"] == "list"
    a.put("/api/settings/display", json={"show_split": False})  # other display saves keep it
    a.put("/api/settings", json={"use_last": False})
    assert a.get("/api/settings/display").json()["today_view"] == "table"
    assert a.put("/api/settings/display", json={"today_view": "list"}).json()["today_view"] == "list"


@pytest.mark.parametrize("value", ["grid", "", None, 1, ["list"], {"a": 1}, "TABLE"])
def test_today_view_validation(a, value):
    assert a.put("/api/settings/display", json={"today_view": value}).status_code == 400
    assert a.get("/api/settings/display").json()["today_view"] == "list"


def test_today_view_migrates_old_settings_table(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    c = sqlite3.connect(tmp_path / "old.db")
    c.executescript("CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT,"
                    " use_last INTEGER NOT NULL DEFAULT 1); INSERT INTO settings(user_id) VALUES(1);")
    c.row_factory = sqlite3.Row
    core.init(c)
    core.init(c)  # safe to run twice
    assert c.execute("SELECT today_view FROM settings").fetchone()[0] == "list"
    assert core.read_display(c, 1)["today_view"] == "list"


# ---------- micronutrient targets ----------

def test_micro_targets_defaults_put_and_isolation(a, b):
    m = {x["key"]: x for x in a.get("/api/goals/micros").json()["micros"]}
    assert [k for k in m] == list(core.MICROS)
    assert (m["fiber"]["target"], m["fiber"]["kind"], m["sodium"]["target"], m["sodium"]["kind"]) == (28, "goal", 2300, "limit")
    assert (m["vitamin_d"]["unit"], m["vitamin_d"]["target"]) == ("mcg", 20)
    r = a.put("/api/goals/micros", json={"targets": {"sodium": 1500, "fiber": 35.5}}).json()
    got = {x["key"]: x["target"] for x in r["micros"]}
    assert got["sodium"] == 1500 and got["fiber"] == 35.5 and got["iron"] == 18
    assert a.get("/api/day").json()["micros"]["sodium"]["target"] == 1500
    assert {x["key"]: x["target"] for x in b.get("/api/goals/micros").json()["micros"]}["sodium"] == 2300
    assert a.get("/api/goals").json() == {"kcal": 3000, "carb_pct": 50, "protein_pct": 30, "fat_pct": 20}


@pytest.mark.parametrize("body", [{}, {"targets": {}}, {"targets": {"zinc": 5}}, {"targets": {"iron": 0}},
                                  {"targets": {"iron": -1}}, {"targets": {"iron": "x"}}, {"targets": {"iron": 1e6}},
                                  {"targets": [1]}])
def test_micro_targets_validation(a, body):
    assert a.put("/api/goals/micros", json=body).status_code == 400


# ---------- default search source ----------

def test_search_source_default_save_and_isolation(a, b):
    assert a.get("/api/settings/display").json()["search_source"] == "all"
    for v in ("off", "fdc", "ai", "all", "fdc"):
        assert a.put("/api/settings/display", json={"search_source": v}).json()["search_source"] == v
    a.put("/api/settings/display", json={"show_split": False})  # other display saves keep it
    assert a.get("/api/settings/display").json()["search_source"] == "fdc"
    assert b.get("/api/settings/display").json()["search_source"] == "all"


@pytest.mark.parametrize("value", ["usda", "", None, 1, ["all"], {"a": 1}, "ALL"])
def test_search_source_validation(a, value):
    assert a.put("/api/settings/display", json={"search_source": value}).status_code == 400
    assert a.get("/api/settings/display").json()["search_source"] == "all"


# ---------- auto-match after import ----------

def test_auto_match_default_save_and_isolation(a, b):
    assert a.get("/api/settings/display").json()["auto_match"] == "search"
    for v in ("off", "claude", "search_claude", "search", "off"):
        assert a.put("/api/settings/display", json={"auto_match": v}).json()["auto_match"] == v
    a.put("/api/settings/display", json={"show_split": False, "search_source": "fdc"})  # other display saves keep it
    assert a.get("/api/settings/display").json()["auto_match"] == "off"
    assert b.get("/api/settings/display").json()["auto_match"] == "search"


@pytest.mark.parametrize("value", ["", None, "Claude", "search claude", "search_claude ", "claude_search", "auto", True, 1, ["off"], {"a": 1}, "OFF", "Search"])
def test_auto_match_validation(a, value):
    assert a.put("/api/settings/display", json={"auto_match": value}).status_code == 400
    assert a.get("/api/settings/display").json()["auto_match"] == "search"


def test_auto_match_error_lists_the_values(a):
    r = a.put("/api/settings/display", json={"auto_match": "nope"})
    assert r.status_code == 400
    for v in core.AUTO_MATCHES:
        assert v in r.json()["detail"]
    assert core.AUTO_MATCHES == ("search", "claude", "search_claude", "off")


def test_auto_match_migrates_old_settings_table(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    c = sqlite3.connect(tmp_path / "old.db")
    c.executescript("CREATE TABLE settings(user_id INTEGER PRIMARY KEY, start_screen TEXT NOT NULL DEFAULT 'today', default_meal TEXT,"
                    " use_last INTEGER NOT NULL DEFAULT 1); INSERT INTO settings(user_id) VALUES(1);")
    c.row_factory = sqlite3.Row
    core.init(c)
    core.init(c)  # safe to run twice
    assert c.execute("SELECT auto_match FROM settings").fetchone()[0] == "search"
    assert core.read_display(c, 1)["auto_match"] == "search"
    c.execute("UPDATE settings SET auto_match='bogus'")  # a bad stored value reads as the default
    assert core.read_display(c, 1)["auto_match"] == "search"
    for v in core.AUTO_MATCHES:  # every allowed value reads back as stored
        c.execute("UPDATE settings SET auto_match=?", (v,))
        assert core.read_display(c, 1)["auto_match"] == v


def test_display_group_recipes_default_validation_and_per_user(a, b):
    assert a.get("/api/settings/display").json()["group_recipes"] is True
    assert a.put("/api/settings/display", json={"group_recipes": False}).json()["group_recipes"] is False
    assert a.get("/api/settings/display").json()["group_recipes"] is False
    assert b.get("/api/settings/display").json()["group_recipes"] is True
    for bad in ("no", 0, None):
        assert a.put("/api/settings/display", json={"group_recipes": bad}).status_code == 400
    assert a.get("/api/settings/display").json()["group_recipes"] is False
    assert a.put("/api/settings/display", json={"group_recipes": True}).json()["group_recipes"] is True
