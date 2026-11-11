import httpx
import pytest

from app import lookup

OFF_FULL = {"status": 1, "product": {
    "code": "0073472001011", "product_name": "Whole Grain Bread", "brands": "Sara Lee, Other",
    "serving_size": "1 slice (34 g)", "serving_quantity": 34,
    "nutriments": {"energy-kcal_serving": 90, "carbohydrates_serving": 17, "proteins_serving": 4,
                   "fat_serving": 1.5, "fiber_serving": 3, "energy-kcal_100g": 265}}}
OFF_PER100 = {"status": 1, "product": {
    "code": "4006381333931", "product_name": "Cola", "serving_size": "250 ml", "serving_quantity": 250,
    "serving_quantity_unit": "ml",
    "nutriments": {"energy_100g": 180, "carbohydrates_100g": 10.6, "proteins_100g": 0, "fat_100g": 0}}}
OFF_NO_NUTRIMENTS = {"status": 1, "product": {"code": "073472001011", "product_name": "Mystery", "nutriments": {}}}
OFF_MISSING = {"status": 0, "status_verbose": "product not found"}


def fdc_item(**kw):
    item = {"fdcId": 123, "description": "PEANUT BUTTER", "brandOwner": "Acme Foods", "gtinUpc": "073472001011",
            "servingSize": 30.0, "servingSizeUnit": "g", "householdServingFullText": "2 tbsp",
            "foodNutrients": [{"nutrientNumber": "208", "value": 600}, {"nutrientNumber": "205", "value": 20},
                              {"nutrientNumber": "203", "value": 25}, {"nutrientNumber": "204", "value": 50},
                              {"nutrientNumber": "291", "value": 6.6}]}
    return item | kw


def install(monkeypatch, off=None, fdc=None, off_error=False, fdc_error=False):
    """Route OFF and FDC requests to canned JSON. Returns the list of seen requests."""
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "world.openfoodfacts.org":
            if off_error:
                raise httpx.ConnectError("down")
            return httpx.Response(404 if off is None else 200, json=off or OFF_MISSING)
        if fdc_error:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json={"foods": fdc or []})

    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(handler))
    return seen


# ---------- normalize_barcode ----------

def test_normalize_valid_upca():
    r = lookup.normalize_barcode("073472001011")
    assert r["valid"] and r["note"] == ""
    assert r["candidates"] == ["073472001011", "0073472001011", "00073472001011"]


def test_normalize_bad_check_digit():
    r = lookup.normalize_barcode("0 73472 00101 0")
    assert not r["valid"] and "typo" in r["note"] and "expected 1" in r["note"]
    assert r["candidates"][0] == "073472001010"


def test_normalize_eleven_digits_and_leading_zero_variant():
    r = lookup.normalize_barcode("07347200101")
    assert r["valid"] and "added" in r["note"] and r["candidates"][0] == "073472001011"
    assert lookup.normalize_barcode("0073472001011")["candidates"][0] == "073472001011"
    assert lookup.normalize_barcode("4006381333931")["candidates"] == ["4006381333931", "04006381333931"]


@pytest.mark.parametrize("raw", ["", "abc", "12345", None])
def test_normalize_rejects_junk(raw):
    r = lookup.normalize_barcode(raw)
    assert r["candidates"] == [] and not r["valid"] and r["note"]


def _upce(n, six, body):
    """Build a UPC-E from number system, 6 digits and the expected 11 digit UPC-A body."""
    check = lookup.check_digit(body)
    return n + six + str(check), body + str(check)


@pytest.mark.parametrize("n,six,body", [
    ("0", "425261", "04210000526"),   # last digit 0-2: manufacturer d1 d2 d6, then 0000
    ("0", "123453", "01230000045"),   # 3
    ("0", "123454", "01234000005"),   # 4
    ("0", "123456", "01234500006"),   # 5-9
    ("1", "123459", "11234500009"),
])
def test_normalize_expands_upce(n, six, body):
    code, upca = _upce(n, six, body)
    r = lookup.normalize_barcode(code)
    assert r["valid"] and r["candidates"][0] == upca and len(upca) == 12
    assert upca.zfill(13) in r["candidates"] and code.zfill(13) in r["candidates"]


def test_normalize_known_upce_values():
    assert lookup.normalize_barcode("04252614")["candidates"][0] == "042100005264"
    assert lookup.normalize_barcode("01234565")["candidates"][0] == "012345000065"


def test_normalize_ean8_and_bad_check_digit():
    r = lookup.normalize_barcode("20123451")  # starts with 2: EAN-8 only
    assert r["valid"] and r["candidates"] == ["0000020123451", "20123451"]
    r = lookup.normalize_barcode("01234566")  # wrong check digit: flagged, not expanded
    assert not r["valid"] and "wrong" in r["note"] and r["candidates"][0] == "0000001234566"
    assert lookup.normalize_barcode("1234567")["candidates"] == []


# ---------- parse_serving ----------

@pytest.mark.parametrize("text,amount,unit,g,ml", [
    ("1 slice (34 g)", 1, "slice", 34, None),
    ("2 tbsp (30g)", 2, "tbsp", 30, None),
    ("2 TBSP (30g)", 2, "tbsp", 30, None),
    ("8 fl oz (240 ml)", 8, "floz", None, 240),
    ("1 cup (240ml)", 1, "cup", None, 240),
    ("28 g", 28, "g", 28, None),
    ("3/4 cup (30 g)", 0.75, "cup", 30, None),
    ("1 1/2 cups (45 g)", 1.5, "cup", 45, None),
    ("1 bar (40 g)", 1, "bar", 40, None),
    ("about 15 pieces (30 g)", 15, "piece", 30, None),
    ("1.5 oz (42g)", 1.5, "oz", 42, None),
])
def test_parse_serving(text, amount, unit, g, ml):
    r = lookup.parse_serving(text)
    assert r["serving_amount"] == pytest.approx(amount) and r["serving_unit"] == unit
    assert r["serving_g"] == (pytest.approx(g) if g else None)
    if ml:
        assert r["serving_ml"] == pytest.approx(ml)
    assert r["label_text"] == text


def test_parse_serving_fallbacks():
    assert lookup.parse_serving("2 tbsp", serving_g=30)["serving_g"] == 30
    assert lookup.parse_serving("", serving_g=30) == {
        "serving_amount": 30, "serving_unit": "g", "serving_g": 30, "serving_ml": None, "label_text": "30 g"}
    r = lookup.parse_serving("one scoop")
    assert (r["serving_amount"], r["serving_unit"], r["label_text"]) == (1.0, "serving", "one scoop")


# ---------- barcode ----------

async def test_barcode_found_in_off(monkeypatch):
    install(monkeypatch, off=OFF_FULL)
    r = await lookup.barcode("073472001011")
    f = r["food"]
    assert r["valid"] and r["note"] == ""
    assert (f["source"], f["barcode"], f["name"], f["brand"]) == ("off", "073472001011", "Whole Grain Bread", "Sara Lee")
    assert (f["serving_amount"], f["serving_unit"], f["serving_g"], f["label_text"]) == (1, "slice", 34, "1 slice (34 g)")
    assert (f["kcal"], f["carbs"], f["protein"], f["fat"], f["fiber"]) == (90, 17, 4, 1.5, 3)


async def test_barcode_off_scales_per_100_and_kj(monkeypatch):
    install(monkeypatch, off=OFF_PER100)
    f = (await lookup.barcode("4006381333931"))["food"]
    assert (f["serving_unit"], f["serving_ml"], f["serving_g"]) == ("ml", 250, None)
    assert f["kcal"] == pytest.approx(107.55, abs=0.01)  # 180 kJ per 100 ml, 250 ml
    assert f["carbs"] == 26.5 and f["fiber"] is None


async def test_barcode_missing_nutriments_falls_back_to_usda(monkeypatch):
    install(monkeypatch, off=OFF_NO_NUTRIMENTS, fdc=[fdc_item()])
    r = await lookup.barcode("073472001011")
    assert r["food"]["source"] == "fdc"
    assert "no nutrition data" in r["note"]


async def test_barcode_missing_nutriments_everywhere(monkeypatch):
    install(monkeypatch, off=OFF_NO_NUTRIMENTS)
    r = await lookup.barcode("073472001011")
    assert r["food"] is None and "no nutrition data" in r["note"] and "Not found" in r["note"]


async def test_barcode_fallback_to_usda_scales_per_100g(monkeypatch):
    seen = install(monkeypatch, off=None, fdc=[fdc_item(gtinUpc="999"), fdc_item()])
    r = await lookup.barcode("073472001011")
    f = r["food"]
    assert (f["source"], f["source_id"], f["name"], f["brand"]) == ("fdc", "123", "Peanut Butter", "Acme Foods")
    assert (f["serving_amount"], f["serving_unit"], f["serving_g"], f["label_text"]) == (2, "tbsp", 30, "2 tbsp (30 g)")
    assert (f["kcal"], f["carbs"], f["protein"], f["fat"], f["fiber"]) == (180, 6, 7.5, 15, 1.98)
    assert f["barcode"] == "073472001011"
    fdc_req = seen[-1]
    assert fdc_req.url.params["api_key"] == "DEMO_KEY" and fdc_req.url.params["dataType"] == "Branded"
    assert fdc_req.headers["user-agent"] == "macrolog/0.1"


async def test_barcode_usda_matches_gtin_ignoring_leading_zeros(monkeypatch):
    install(monkeypatch, fdc=[fdc_item(gtinUpc="0073472001011")])
    assert (await lookup.barcode("073472001011"))["food"]["source"] == "fdc"


async def test_barcode_not_found(monkeypatch):
    install(monkeypatch, fdc=[fdc_item(gtinUpc="111111111111")])
    r = await lookup.barcode("073472001011")
    assert r["food"] is None and r["valid"] and "Not found" in r["note"]


async def test_barcode_bad_check_digit_still_looks_up(monkeypatch):
    install(monkeypatch, off=OFF_FULL)
    r = await lookup.barcode("073472001010")
    assert not r["valid"] and "typo" in r["note"] and r["food"]["name"] == "Whole Grain Bread"


async def test_barcode_network_errors_never_raise(monkeypatch):
    install(monkeypatch, off_error=True, fdc_error=True)
    r = await lookup.barcode("073472001011")
    assert r["food"] is None
    assert "Open Food Facts unreachable" in r["note"] and "USDA FoodData Central unreachable" in r["note"]


async def test_barcode_off_down_usda_answers(monkeypatch):
    install(monkeypatch, off_error=True, fdc=[fdc_item()])
    r = await lookup.barcode("073472001011")
    assert r["food"]["source"] == "fdc" and "Open Food Facts unreachable" in r["note"]


async def test_barcode_invalid_input_makes_no_request(monkeypatch):
    seen = install(monkeypatch)
    r = await lookup.barcode("12ab")
    assert r["food"] is None and not r["valid"] and seen == []


# ---------- search ----------

async def test_search_returns_foods(monkeypatch):
    seen = install(monkeypatch, fdc=[fdc_item(), fdc_item(fdcId=2, servingSize=None, servingSizeUnit=None,
                                                          householdServingFullText=None),
                                     {"fdcId": 3, "description": "No energy", "foodNutrients": []}])
    monkeypatch.setenv("FDC_API_KEY", "KEY")
    res = await lookup.search("peanut butter", limit=5)
    assert [f["source_id"] for f in res] == ["123", "2"]
    assert res[1]["label_text"] == "100 g" and res[1]["kcal"] == 600
    assert seen[0].url.params["api_key"] == "KEY" and seen[0].url.params["pageSize"] == "5"


async def test_search_ml_serving_and_network_error(monkeypatch):
    install(monkeypatch, fdc=[fdc_item(servingSize=240, servingSizeUnit="ml", householdServingFullText="1 cup")])
    f = (await lookup.search("milk"))[0]
    assert (f["serving_unit"], f["serving_ml"], f["kcal"]) == ("cup", 240, 1440)
    install(monkeypatch, fdc_error=True)
    assert await lookup.search("milk") == []
    assert await lookup.search("   ") == []


async def test_search_off_builds_foods_and_never_raises(monkeypatch):
    seen = []
    product = {"code": "5000159407236", "product_name": "Rice Pudding", "brands": "Ambrosia, Other",
               "serving_size": "1 pot (125 g)", "serving_quantity": 125,
               "nutriments": {"energy-kcal_100g": 100, "carbohydrates_100g": 16, "proteins_100g": 3, "fat_100g": 2.5}}

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"products": [product, {"code": "1", "product_name": "No data"}, {"product_name": "No code"}]})

    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(handler))
    res = await lookup.search_off("rice pudding", limit=5)
    assert [(f["source"], f["source_id"], f["name"], f["brand"]) for f in res] == [("off", "5000159407236", "Rice Pudding", "Ambrosia")]
    assert res[0]["kcal"] == 125 and res[0]["barcode"] == "5000159407236"
    q = seen[0].url.params
    assert seen[0].url.host == "world.openfoodfacts.org" and seen[0].url.path == "/cgi/search.pl"
    assert q["search_terms"] == "rice pudding" and q["json"] == "1" and q["page_size"] == "5"
    install(monkeypatch, off_error=True)
    assert await lookup.search_off("rice") == []
    assert await lookup.search_off("  ") == []
