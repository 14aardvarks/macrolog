"""Refresh Nutrients: fill only null micronutrients from the original source, never touch anything else."""
import json
from pathlib import Path

import httpx
import pytest

from app import core, db, lookup
from tests.test_core import BREAD, a, b, env, food  # noqa: F401

FIX = Path(__file__).parent / "fixtures"
OFF = json.loads((FIX / "off_micros.json").read_text())
FDC = json.loads((FIX / "fdc_micros.json").read_text())
SOUP = FDC["foods"][0]
MICROS = core.MICROS


def detail(item):
    """The FDC search hit reshaped as the /food/{id} detail answer (nested nutrient, amount)."""
    nutrients = [{"nutrient": {"id": n.get("nutrientId"), "number": n.get("nutrientNumber"), "unitName": n.get("unitName")},
                  "amount": n["value"]} for n in item["foodNutrients"]]
    return {**item, "foodNutrients": nutrients}


def mock(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)
    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(wrapped))
    return seen


def saved(**kw):
    base = {"source": "off", "source_id": "3017620422003", "barcode": "3017620422003", "name": "Hazelnut Spread",
            "serving_amount": 15, "serving_unit": "g", "serving_g": 15, "kcal": 80, "carbs": 8, "protein": 1, "fat": 4.5}
    with db.conn() as c:
        return core.save_food(c, core.normalize_food({**base, **kw}))


def off_ok(request):
    return httpx.Response(200, json=OFF)


def refresh(client, f):
    return client.post(f"/api/foods/{f['id']}/refresh-nutrients")


def test_off_fills_only_null_micros_and_nothing_else(a, monkeypatch):
    seen = mock(monkeypatch, off_ok)
    f = saved(fiber=99, sodium=1)
    r = refresh(a, f)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filled"] == ["sugars", "saturated_fat", "potassium", "calcium", "iron", "vitamin_d"]
    got = body["food"]
    assert got["fiber"] == 99 and got["sodium"] == 1  # existing values stay
    assert got["cholesterol"] is None  # the source has none either
    assert got["potassium"] == 60 and got["sugars"] == pytest.approx(8.45, abs=0.01)
    for k in ("name", "brand", "kcal", "carbs", "protein", "fat", "serving_amount", "serving_unit", "serving_g"):
        assert got[k] == f[k]
    assert "3017620422003" in seen[0]
    assert a.get(f"/api/foods/{f['id']}").json()["calcium"] == pytest.approx(16.2)


def test_second_refresh_fills_nothing_and_says_so(a, monkeypatch):
    mock(monkeypatch, off_ok)
    f = saved()
    assert refresh(a, f).json()["filled"]
    r = refresh(a, f).json()
    assert r["filled"] == [] and "no more data" in r["message"]


def test_source_with_no_more_data_returns_empty_list(a, monkeypatch):
    mock(monkeypatch, lambda req: httpx.Response(200, json={"status": 1, "product": {
        "code": "3017620422003", "serving_size": "15 g", "serving_quantity": 15,
        "nutriments": {"energy-kcal_100g": 500}}}))
    r = refresh(a, saved()).json()
    assert r["filled"] == [] and r["message"] == "The source has no more data for this food"


def test_used_food_can_be_refreshed_while_normal_edit_stays_locked(a, monkeypatch):
    mock(monkeypatch, off_ok)
    f = food(a, {**BREAD, "barcode": "3017620422003", "serving_g": 15, "serving_amount": 15, "serving_unit": "g", "fiber": None})
    a.post("/api/entries", json={"food_id": f["id"], "amount": 15, "unit": "g"})
    assert a.patch(f"/api/foods/{f['id']}", json={"sugars": 5}).status_code == 409
    r = refresh(a, f)
    assert r.status_code == 200 and "sugars" in r.json()["filled"]
    assert r.json()["food"]["kcal"] == BREAD["kcal"]  # custom food values from the source never replace macros


def test_fdc_by_id_uses_detail_endpoint_and_scales(a, monkeypatch):
    seen = mock(monkeypatch, lambda req: httpx.Response(200, json=detail(SOUP)))
    f = saved(source="fdc", source_id="777", barcode=None, name="Tomato Soup", serving_amount=1, serving_unit="cup",
              serving_g=245, kcal=100, fiber=None, sodium=5)
    r = refresh(a, f).json()
    assert "/fdc/v1/food/777" in seen[0] and "api_key=" in seen[0]
    assert "sodium" not in r["filled"] and r["food"]["sodium"] == 5
    assert r["food"]["potassium"] == 490 and r["food"]["fiber"] == pytest.approx(1.96)


def test_different_serving_is_scaled_by_weight_or_refused(a, monkeypatch):
    mock(monkeypatch, lambda req: httpx.Response(200, json=detail(SOUP)))
    half = saved(source="fdc", source_id="777", barcode=None, name="Half Soup", serving_amount=0.5, serving_unit="cup", serving_g=122.5)
    assert refresh(a, half).json()["food"]["potassium"] == 245
    other = saved(source="fdc", source_id="778", barcode=None, name="Odd", serving_amount=2, serving_unit="slice", serving_g=None)
    mock(monkeypatch, lambda req: httpx.Response(200, json=detail(SOUP)))
    r = refresh(a, other)
    assert r.status_code == 409 and "serving size" in r.json()["detail"]
    assert a.get(f"/api/foods/{other['id']}").json()["potassium"] is None


def test_manual_food_without_barcode_has_nothing_to_look_up(a, monkeypatch):
    seen = mock(monkeypatch, off_ok)
    r = refresh(a, food(a))
    assert r.status_code == 400 and "nothing to look up" in r.json()["detail"]
    assert not seen


def test_custom_food_with_barcode_is_found_by_barcode_and_creator_only(a, b, monkeypatch):
    mock(monkeypatch, off_ok)
    f = food(a, {**BREAD, "barcode": "3017620422003", "serving_g": 15, "serving_amount": 15, "serving_unit": "g"})
    assert refresh(b, f).status_code == 403
    assert refresh(a, f).status_code == 200


def test_shared_off_food_any_user_and_unknown_food(a, b, monkeypatch):
    mock(monkeypatch, off_ok)
    f = saved()
    assert refresh(b, f).status_code == 200
    assert a.post("/api/foods/9999/refresh-nutrients").status_code == 404


def test_complete_food_skips_the_network(a, monkeypatch):
    seen = mock(monkeypatch, off_ok)
    f = saved(**{k: 1 for k in MICROS})
    r = refresh(a, f).json()
    assert r["filled"] == [] and "already has every nutrient" in r["message"] and not seen


@pytest.mark.parametrize("src,sid", [("off", "3017620422003"), ("fdc", "777")])
def test_rate_limit_and_network_errors(a, monkeypatch, src, sid):
    f = saved(source=src, source_id=sid, barcode=None, name="X" + src, serving_g=15)
    mock(monkeypatch, lambda req: httpx.Response(429, json={}))
    r = refresh(a, f)
    assert r.status_code == 429 and "rate limit" in r.json()["detail"]
    mock(monkeypatch, lambda req: httpx.Response(500))
    assert refresh(a, f).status_code == 502

    def boom(req):
        raise httpx.ConnectError("down")
    mock(monkeypatch, boom)
    assert refresh(a, f).status_code == 502
    assert a.get(f"/api/foods/{f['id']}").json()["sodium"] is None


def test_source_not_found_is_a_message_not_an_error(a, monkeypatch):
    mock(monkeypatch, lambda req: httpx.Response(404, json={}))
    r = refresh(a, saved(source="fdc", source_id="123", barcode=None, name="Gone"))
    assert r.status_code == 200 and r.json()["filled"] == [] and r.json()["message"]


def test_refresh_kind():
    assert lookup.refresh_kind({"source": "off", "source_id": "1"}) == "off"
    assert lookup.refresh_kind({"source": "fdc", "source_id": "12"}) == "fdc"
    assert lookup.refresh_kind({"source": "custom", "barcode": "3017620422003"}) == "barcode"
    assert lookup.refresh_kind({"source": "ai", "barcode": None}) is None
    assert lookup.refresh_kind({"source": "custom", "barcode": "12"}) is None
