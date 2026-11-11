import json
import threading
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai, db, deps

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
SECRET = "sk-ant-secret-key-123"

GOOD = {"name": "Creamy Peanut Butter", "brand": "Nutty Co", "serving_text": "2 tbsp (32 g)", "serving_amount": 2,
        "serving_unit": "tbsp", "serving_g": 32, "serving_ml": None, "kcal": 190, "carbs": 7, "protein": 8,
        "fat": 16, "fiber": 2, "confidence": "Label is sharp and fully readable."}


def api_reply(tool_input, usage=None, stop="tool_use"):
    return {"id": "msg_01", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": "Reading the label."},
                        {"type": "tool_use", "id": "toolu_01", "name": ai.TOOL_NAME, "input": tool_input}],
            "stop_reason": stop, "usage": usage or {"input_tokens": 1500, "output_tokens": 120}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("AI_MONTHLY_REQUEST_CAP", raising=False)
    with db.conn() as c:
        db.init_shared(c)
        ai.init(c)
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a'), (2, 'b')")
    state = {"user": {"id": 1, "username": "a", "display_name": "A"}, "requests": [],
             "handler": lambda req: httpx.Response(200, json=api_reply(GOOD))}

    def handler(req):
        state["requests"].append(req)
        return state["handler"](req)

    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(handler))
    app = FastAPI()
    app.include_router(ai.router)
    app.dependency_overrides[deps.current_user] = lambda: state["user"]
    state["client"] = TestClient(app)
    return state


def post(env, files=None, **data):
    files = [("images", ("label.jpg", JPEG, "image/jpeg"))] if files is None else files
    return env["client"].post("/api/ai/label", files=files, data=data)


def usage_rows():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ai_usage ORDER BY id")]


# ---------- status and config ----------

def test_enabled_follows_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai.enabled() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    assert ai.enabled() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert ai.enabled() is True


def test_status(env, monkeypatch):
    for k in ("AI_PRICE_IN_PER_MTOK", "AI_PRICE_OUT_PER_MTOK"):
        monkeypatch.delenv(k, raising=False)
    r = env["client"].get("/api/ai/status")
    assert r.json() == {"enabled": True, "used_this_month": 0, "cap": 100, "remaining": 100, "model": "claude-haiku-5-5",
                        "price_known": False, "est_cost_label": None, "cost_this_month": None}
    assert SECRET not in r.text


def test_status_without_key(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("AI_MODEL", "claude-x")
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "7")
    r = env["client"].get("/api/ai/status").json()
    assert (r["enabled"], r["used_this_month"], r["cap"], r["remaining"], r["model"]) == (False, 0, 7, 7, "claude-x")


def test_bad_cap_env_falls_back(env, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "lots")
    assert ai.cap() == 100


def test_routes_require_login(env):
    from fastapi import HTTPException

    def deny():
        raise HTTPException(401, "Not signed in")

    env["client"].app.dependency_overrides[deps.current_user] = deny
    assert env["client"].get("/api/ai/status").status_code == 401
    assert post(env).status_code == 401
    assert env["requests"] == []


# ---------- cost ----------

@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")


def test_estimate_math_and_images_param(env, priced):
    st = env["client"].get("/api/ai/status").json()
    assert st["price_known"] is True
    # 1 image: 1600 + 700 = 2300 in, 400 out: 2300*1/1e6 + 400*5/1e6
    assert st["est_cost_label"] == pytest.approx(0.0023 + 0.002)
    three = env["client"].get("/api/ai/status", params={"images": 3}).json()
    assert three["est_cost_label"] == pytest.approx((3 * 1600 + 700) / 1e6 + 0.002)
    assert env["client"].get("/api/ai/status", params={"images": 4}).status_code == 422
    assert env["client"].get("/api/ai/status", params={"images": 0}).status_code == 422


def test_cost_this_month_uses_real_tokens_for_the_household(env, priced):
    post(env)
    env["user"] = {"id": 2, "username": "b", "display_name": "B"}
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(GOOD, {"input_tokens": 1000, "output_tokens": 200}))
    post(env)
    st = env["client"].get("/api/ai/status").json()
    assert st["used_this_month"] == 2 and st["remaining"] == 98
    assert st["cost_this_month"] == pytest.approx((2500 * 1 + 320 * 5) / 1e6)


def test_cost_ignores_other_months(env, priced):
    with db.conn() as c:
        c.execute("INSERT INTO ai_usage(user_id, at, input_tokens, output_tokens) VALUES (1, '2001-01-05T00:00:00', 900000, 900000)")
    assert env["client"].get("/api/ai/status").json()["cost_this_month"] == 0


def test_price_unknown_gives_null_costs(env, monkeypatch):
    monkeypatch.delenv("AI_PRICE_OUT_PER_MTOK", raising=False)
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", "1")  # one of two is not enough
    post(env)
    st = env["client"].get("/api/ai/status").json()
    assert st["price_known"] is False and st["est_cost_label"] is None and st["cost_this_month"] is None
    assert post(env).json()["cost"] is None


@pytest.mark.parametrize("bad", ["abc", "-1", "nan", "inf", ""])
def test_bad_price_env_is_unknown(env, monkeypatch, bad):
    monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", bad)
    monkeypatch.setenv("AI_PRICE_OUT_PER_MTOK", "5")
    assert ai.prices() is None


def test_label_response_has_actual_cost(env, priced):
    body = post(env).json()
    assert body["cost"] == pytest.approx((1500 * 1 + 120 * 5) / 1e6)


def test_remaining_is_zero_at_cap(env, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "1")
    post(env)
    assert env["client"].get("/api/ai/status").json()["remaining"] == 0


# ---------- success ----------

def test_success_shape(env):
    r = post(env)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"draft", "warnings", "used_this_month", "cap", "input_tokens", "output_tokens", "cost"}
    assert (body["input_tokens"], body["output_tokens"]) == (1500, 120)
    d = body["draft"]
    assert "id" not in d
    assert d["source"] == "ai" and d["barcode"] is None
    assert d["name"] == "Creamy Peanut Butter" and d["brand"] == "Nutty Co"
    assert (d["serving_amount"], d["serving_unit"], d["serving_g"]) == (2, "tbsp", 32)
    assert d["serving_ml"] == pytest.approx(29.5736, abs=0.01)  # derived by lookup.parse_serving
    assert d["label_text"] == "2 tbsp (32 g)"
    assert (d["kcal"], d["carbs"], d["protein"], d["fat"], d["fiber"]) == (190, 7, 8, 16, 2)
    assert body["used_this_month"] == 1 and body["cap"] == 100
    assert body["warnings"] == ["Claude's note: Label is sharp and fully readable."]


def test_draft_is_not_saved_and_tokens_recorded(env):
    post(env)
    rows = usage_rows()
    assert len(rows) == 1
    assert (rows[0]["user_id"], rows[0]["input_tokens"], rows[0]["output_tokens"]) == (1, 1500, 120)
    with db.conn() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "foods" not in tables


def test_request_sent_to_anthropic(env):
    post(env, files=[("images", ("a.jpg", JPEG, "image/jpeg")), ("images", ("b.png", PNG, "image/png")),
                     ("images", ("c.webp", WEBP, "image/webp"))], hint="  organic\nvalley ")
    req = env["requests"][0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == SECRET
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert req.headers["content-type"] == "application/json"
    p = json.loads(req.content)
    assert p["model"] == "claude-haiku-5-5" and 500 <= p["max_tokens"] <= 1000
    assert p["tool_choice"] == {"type": "tool", "name": ai.TOOL_NAME}
    assert len(p["tools"]) == 1 and p["tools"][0]["input_schema"]["additionalProperties"] is False
    content = p["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "image", "text"]
    assert [b["source"]["media_type"] for b in content[:3]] == ["image/jpeg", "image/png", "image/webp"]
    assert content[0]["source"]["type"] == "base64"
    text = content[3]["text"]
    assert "SERVING" in text and "null" in text and "per 100 g" in text and "organic valley" in text


def test_model_env(env, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "claude-other")
    post(env)
    assert json.loads(env["requests"][0].content)["model"] == "claude-other"


def test_non_haiku_model_uses_auto_tool_choice(env, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-5-5")
    post(env)
    p = json.loads(env["requests"][0].content)
    assert p["tool_choice"] == {"type": "auto"} and p["tools"][0]["strict"] is True


def test_haiku_model_id_any_case_forces_tool(env, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "Claude-Haiku-9")
    post(env)
    assert json.loads(env["requests"][0].content)["tool_choice"] == {"type": "tool", "name": ai.TOOL_NAME}


def test_auto_model_without_tool_use_is_502(env, monkeypatch):
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-5-5")
    reply = {"content": [{"type": "text", "text": "Sorry"}], "stop_reason": "end_turn", "usage": {}}
    env["handler"] = lambda req: httpx.Response(200, json=reply)
    r = post(env)
    assert r.status_code == 502 and "readable result" in r.json()["detail"]


def test_serving_text_missing_builds_from_amount_unit(env):
    env["handler"] = lambda req: httpx.Response(200, json=api_reply({**GOOD, "serving_text": None, "serving_g": None}))
    d = post(env).json()["draft"]
    assert (d["serving_amount"], d["serving_unit"], d["label_text"]) == (2, "tbsp", "2 tbsp")


# ---------- warnings ----------

def test_calorie_mismatch_warns(env):
    env["handler"] = lambda req: httpx.Response(200, json=api_reply({**GOOD, "kcal": 400, "confidence": ""}))
    w = post(env).json()["warnings"]
    assert len(w) == 1 and "20 percent" in w[0]


def test_calorie_within_tolerance_is_quiet(env):
    # 4*7 + 4*8 + 9*16 = 204, label says 190 (under 20 percent)
    env["handler"] = lambda req: httpx.Response(200, json=api_reply({**GOOD, "confidence": ""}))
    assert post(env).json()["warnings"] == []


def test_missing_serving_warns(env):
    tool = {**GOOD, "serving_text": None, "serving_amount": None, "serving_unit": None, "serving_g": None, "confidence": ""}
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(tool))
    r = post(env).json()
    assert any("Serving size is missing" in w for w in r["warnings"])
    assert r["draft"]["serving_amount"] == 1 and r["draft"]["serving_unit"] == "serving"


def test_null_values_stay_null_and_warn(env):
    tool = {**GOOD, "fiber": None, "carbs": None, "confidence": ""}
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(tool))
    r = post(env).json()
    assert r["draft"]["fiber"] is None and r["draft"]["carbs"] is None
    assert r["warnings"] == ["Not visible on the label, left blank: carbs, fiber."]


def test_all_null_label(env):
    tool = {k: None for k in GOOD}
    tool["confidence"] = "Photo is too blurry"
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(tool))
    r = post(env)
    assert r.status_code == 200
    w = " ".join(r.json()["warnings"])
    assert "Serving size is missing" in w and "name was not visible" in w and "blurry" in w


def test_negative_and_absurd_values(env):
    tool = {**GOOD, "kcal": 90000, "protein": -3, "fat": 999, "confidence": ""}
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(tool))
    w = " ".join(post(env).json()["warnings"])
    assert "kcal of 90000" in w and "protein is negative" in w and "fat of 999" in w


def test_macros_heavier_than_serving_and_fiber_over_carbs(env):
    tool = {**GOOD, "serving_text": "5 g", "serving_g": 5, "serving_amount": 5, "serving_unit": "g",
            "carbs": 7, "fiber": 9, "confidence": ""}
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(tool))
    w = " ".join(post(env).json()["warnings"])
    assert "more than the serving weight" in w and "Fiber is higher" in w


def test_junk_number_types_become_null(env):
    tool = {**GOOD, "kcal": "190", "carbs": True, "protein": "n/a", "fat": float("inf") if False else 16, "confidence": ""}
    env["handler"] = lambda req: httpx.Response(200, json=api_reply(tool))
    d = post(env).json()["draft"]
    assert d["kcal"] == 190 and d["carbs"] is None and d["protein"] is None


# ---------- barcode ----------

def test_barcode_passthrough_normalized(env):
    d = post(env, barcode="0 49000 02890 4").json()["draft"]  # Coca-Cola can UPC, valid check digit
    assert d["barcode"] == "049000028904"


def test_barcode_eleven_digits_gets_check_digit(env):
    assert post(env, barcode="04900002890").json()["draft"]["barcode"] == "049000028904"


def test_invalid_barcode_dropped_with_warning(env):
    r = post(env, barcode="049000028905").json()
    assert r["draft"]["barcode"] is None
    assert "Barcode not attached" in r["warnings"][0]


def test_blank_barcode_ignored(env):
    r = post(env, barcode="  ").json()
    assert r["draft"]["barcode"] is None and not any("Barcode" in w for w in r["warnings"])


# ---------- upload validation ----------

def test_no_key_503(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    r = post(env)
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert env["requests"] == [] and usage_rows() == []


def test_no_images_400(env):
    r = env["client"].post("/api/ai/label", data={"hint": "x"})
    assert r.status_code == 400 and "1 to 3" in r.json()["detail"]


def test_too_many_images_400(env):
    r = post(env, files=[("images", (f"{i}.jpg", JPEG, "image/jpeg")) for i in range(4)])
    assert r.status_code == 400 and "At most 3" in r.json()["detail"]
    assert env["requests"] == []


def test_oversize_413(env):
    big = b"\xff\xd8\xff" + b"\x00" * ai.MAX_BYTES
    r = post(env, files=[("images", ("big.jpg", big, "image/jpeg"))])
    assert r.status_code == 413 and "5 MB" in r.json()["detail"]
    assert env["requests"] == [] and usage_rows() == []


def test_exactly_5mb_allowed(env):
    ok = b"\xff\xd8\xff" + b"\x00" * (ai.MAX_BYTES - 3)
    assert post(env, files=[("images", ("ok.jpg", ok, "image/jpeg"))]).status_code == 200


def test_wrong_content_type_400(env):
    r = post(env, files=[("images", ("a.pdf", b"%PDF-1.4", "application/pdf"))])
    assert r.status_code == 400 and "not an image" in r.json()["detail"]
    assert env["requests"] == []


def test_magic_number_mismatch_400(env):
    r = post(env, files=[("images", ("fake.jpg", b"<html>not really an image</html>", "image/jpeg"))])
    assert r.status_code == 400 and "JPEG, PNG or WebP" in r.json()["detail"]
    assert env["requests"] == [] and usage_rows() == []


def test_unsupported_image_format_400(env):
    r = post(env, files=[("images", ("a.gif", b"GIF89a" + b"\x00" * 20, "image/gif"))])
    assert r.status_code == 400


def test_declared_type_wrong_but_bytes_ok_uses_sniffed_type(env):
    post(env, files=[("images", ("a.png", JPEG, "image/png"))])
    block = json.loads(env["requests"][0].content)["messages"][0]["content"][0]
    assert block["source"]["media_type"] == "image/jpeg"


# ---------- cap ----------

def test_cap_reached_429(env, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "2")
    assert post(env).status_code == 200
    env["user"] = {"id": 2, "username": "b", "display_name": "B"}  # household wide, other user counts too
    assert post(env).status_code == 200
    r = post(env)
    assert r.status_code == 429 and "Monthly Claude limit reached (2" in r.json()["detail"]
    assert len(env["requests"]) == 2 and len(usage_rows()) == 2
    assert env["client"].get("/api/ai/status").json()["used_this_month"] == 2


def test_cap_counts_calendar_month_only(env, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "1")
    with db.conn() as c:
        c.execute("INSERT INTO ai_usage(user_id, at) VALUES (1, '2000-01-15T10:00:00')")
    assert post(env).status_code == 200
    assert post(env).status_code == 429


def test_month_bounds_december():
    lo, hi = ai._month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert (lo, hi) == ("2026-12-01T00:00:00", "2027-01-01T00:00:00")


def test_zero_cap_blocks_everything(env, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "0")
    assert post(env).status_code == 429


def test_concurrent_reservations_cannot_exceed_cap(env):
    results = []

    def worker():
        results.append(ai.reserve(1, 3))

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len([r for r in results if r is not None]) == 3
    assert len(usage_rows()) == 3


# ---------- upstream failures ----------

@pytest.mark.parametrize("status", [400, 401, 429, 500, 529])
def test_upstream_error_502_no_leak(env, status):
    leak = f"internal detail {SECRET} request_id req_999"
    env["handler"] = lambda req: httpx.Response(status, json={"type": "error", "error": {"message": leak}})
    r = post(env)
    assert r.status_code == 502
    assert SECRET not in r.text and "req_999" not in r.text and "internal detail" not in r.text
    assert str(status) in r.json()["detail"]
    assert usage_rows() == [] and len(env["requests"]) == 1  # reservation released, no retry


def test_network_error_502(env):
    def boom(req):
        raise httpx.ConnectError(f"cannot connect with {SECRET}")

    env["handler"] = boom
    r = post(env)
    assert r.status_code == 502 and SECRET not in r.text and usage_rows() == []


def test_timeout_502(env):
    def slow(req):
        raise httpx.ReadTimeout("slow")

    env["handler"] = slow
    r = post(env)
    assert r.status_code == 502 and "too long" in r.json()["detail"]


def test_non_json_upstream_502(env):
    env["handler"] = lambda req: httpx.Response(200, text="<html>gateway</html>")
    r = post(env)
    assert r.status_code == 502 and "gateway" not in r.text and usage_rows() == []


def test_no_tool_use_block_502_but_usage_kept(env):
    reply = {"content": [{"type": "text", "text": "I cannot read this"}], "stop_reason": "end_turn",
             "usage": {"input_tokens": 900, "output_tokens": 15}}
    env["handler"] = lambda req: httpx.Response(200, json=reply)
    r = post(env)
    assert r.status_code == 502 and "readable result" in r.json()["detail"]
    rows = usage_rows()
    assert len(rows) == 1 and rows[0]["input_tokens"] == 900  # tokens were billed, so it still counts


def test_key_never_in_responses(env):
    for r in (post(env), env["client"].get("/api/ai/status")):
        assert SECRET not in r.text


def test_missing_usage_in_reply_defaults_to_zero(env):
    reply = api_reply(GOOD)
    del reply["usage"]
    env["handler"] = lambda req: httpx.Response(200, json=reply)
    assert post(env).status_code == 200
    assert (usage_rows()[0]["input_tokens"], usage_rows()[0]["output_tokens"]) == (0, 0)
