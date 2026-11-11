import sqlite3

import pytest

from app import admin, ai, auth, config, db

SECRET = "sk-ant-config-secret-value-0001"


@pytest.fixture
def store():
    with db.conn() as c:
        db.init_shared(c)
        config.init(c)


def put(key, value):
    with db.conn() as c:
        config.store(c, key, config.validate(key, value))


# ---------------------------------------------------------------- precedence

def test_precedence_default_env_database(store, monkeypatch):
    assert config.get("ai_model") == "" and config.resolve("ai_model")[1] == "default"
    monkeypatch.setenv("AI_MODEL", "from-env")
    assert config.get("ai_model") == "from-env" and config.resolve("ai_model")[1] == "environment"
    put("ai_model", "from-db")
    assert config.get("ai_model") == "from-db" and config.resolve("ai_model")[1] == "database"
    put("ai_model", None)  # null removes the override
    assert config.get("ai_model") == "from-env"


def test_explicit_default_argument(store):
    assert config.get("oidc_name", "x") == "x"
    assert config.get("fdc_api_key") == "DEMO_KEY"


def test_get_without_table_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("AI_MODEL", "env-only")
    assert config.get("ai_model") == "env-only"  # fresh database without app_config


def test_typed_helpers_match_old_env_parsing(store, monkeypatch):
    for raw, expected in (("0", False), ("off", False), ("No", False), ("", False), ("1", True), ("yes", True)):
        monkeypatch.setenv("LOCAL_LOGIN", raw)
        assert config.flag("local_login") is expected
    monkeypatch.delenv("LOCAL_LOGIN")
    assert config.flag("local_login") is True and config.flag("oidc_allow_signup") is False
    for raw, expected in (("7", 7), ("-1", 100), ("lots", 100)):
        monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", raw)
        assert config.integer("ai_monthly_cap") == expected
    for raw, expected in (("0.5", 0.5), ("-1", None), ("nan", None), ("", None)):
        monkeypatch.setenv("AI_PRICE_IN_PER_MTOK", raw)
        assert config.price("ai_price_in_per_mtok") == expected


def test_database_value_beats_env_for_callers(store, monkeypatch):
    monkeypatch.setenv("LOCAL_LOGIN", "1")
    monkeypatch.setenv("AI_MONTHLY_REQUEST_CAP", "5")
    monkeypatch.setenv("FDC_API_KEY", "ENVKEY")
    put("local_login", False)
    put("ai_monthly_cap", 9)
    put("fdc_api_key", "DBKEY")
    put("oidc_issuer", "https://sso.example.com/app")
    assert auth.local_enabled() is False and ai.cap() == 9
    from app import lookup
    assert lookup.fdc_api_key() == "DBKEY"
    assert auth.oidc_issuer() == "https://sso.example.com/app/"


def test_fdc_key_empty_falls_back_to_demo(store, monkeypatch):
    from app import lookup
    monkeypatch.setenv("FDC_API_KEY", "")
    assert lookup.fdc_api_key() == "DEMO_KEY"
    put("fdc_api_key", "")  # cleared secret
    assert lookup.fdc_api_key() == "DEMO_KEY"


# ---------------------------------------------------------------- secrets

def test_secret_round_trip_is_encrypted_at_rest(store):
    put("ai_global_key", SECRET)
    with db.conn() as c:
        raw = c.execute("SELECT value, secret FROM app_config WHERE key='ai_global_key'").fetchone()
    assert raw["secret"] == 1 and SECRET not in raw["value"] and raw["value"].startswith("gAAAA")
    assert config.get("ai_global_key") == SECRET
    assert ai.api_key() == SECRET


def test_empty_secret_clears_and_beats_env(store, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-xxxxxxxxxxxxxxxx")
    put("ai_global_key", "")
    assert config.get("ai_global_key") == "" and ai.enabled() is False
    assert config.describe()["ai_global_key"] == {"source": "database", "env": "ANTHROPIC_API_KEY",
                                                  "type": "secret", "set": False, "unreadable": False}
    put("ai_global_key", None)
    assert ai.enabled() is True


def test_wrong_secret_key_treats_secret_as_unset(store, monkeypatch, caplog):
    put("oidc_client_secret", SECRET)
    monkeypatch.setenv("SECRET_KEY", "a-completely-different-secret-key-value-123")
    caplog.set_level("DEBUG")
    assert config.get("oidc_client_secret") == ""
    item = config.describe()["oidc_client_secret"]
    assert item["set"] is False and item["unreadable"] is True and item["source"] == "default"
    assert "could not be decrypted" in caplog.text and SECRET not in caplog.text
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "env-fallback")
    assert config.get("oidc_client_secret") == "env-fallback"


def test_encrypt_without_secret_key_refuses(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(config.ConfigError, match="SECRET_KEY"):
        config.encrypt("x")
    assert config.decrypt("gAAAAanything") is None


def test_describe_never_contains_secret_values(store):
    for key in ("ai_global_key", "oidc_client_secret", "fdc_api_key"):
        put(key, SECRET + key)
    text = repr(config.describe())
    assert SECRET not in text


def test_user_secrets(store, monkeypatch):
    with db.conn() as c:
        c.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        assert config.user_secret_state(c, 1, "anthropic") == "unset"
        config.set_user_secret(c, 1, "anthropic", SECRET)
        assert config.user_secret_state(c, 1, "anthropic") == "set"
        assert config.get_user_secret(c, 1, "anthropic") == SECRET
        assert SECRET not in c.execute("SELECT value_enc FROM user_secrets").fetchone()[0]
    monkeypatch.setenv("SECRET_KEY", "another-secret-key-another-secret-key-000")
    with db.conn() as c:
        assert config.user_secret_state(c, 1, "anthropic") == "unreadable"
        assert config.get_user_secret(c, 1, "anthropic") is None
        assert config.delete_user_secret(c, 1, "anthropic") is True


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("key,value,stored", [
    ("local_login", True, "1"), ("local_login", 0, "0"), ("oidc_allow_signup", False, "0"),
    ("ai_monthly_cap", 250, "250"), ("ai_monthly_cap", 0, "0"), ("ai_monthly_cap", 3.0, "3"),
    ("ai_price_in_per_mtok", 0.1, "0.1"), ("ai_price_out_per_mtok", "2", "2"), ("ai_price_in_per_mtok", "", ""),
    ("oidc_issuer", " https://a.example/app/ ", "https://a.example/app/"), ("oidc_issuer", "", ""),
    ("oidc_issuer", "http://10.0.0.5:9000/o/", "http://10.0.0.5:9000/o/"), ("ai_model", "claude-x", "claude-x"),
    ("oidc_client_secret", "", ""), ("ai_global_key", None, None),
])
def test_validate_accepts(key, value, stored):
    assert config.validate(key, value) == stored


@pytest.mark.parametrize("key,value", [
    ("local_login", "yes"), ("local_login", 2), ("ai_monthly_cap", -1), ("ai_monthly_cap", 100001),
    ("ai_monthly_cap", 1.5), ("ai_monthly_cap", True), ("ai_monthly_cap", "many"), ("ai_price_in_per_mtok", -0.1),
    ("ai_price_in_per_mtok", float("nan")), ("oidc_issuer", "ftp://x.example/"), ("oidc_issuer", "javascript:alert(1)"),
    ("oidc_issuer", "https://user:pw@x.example/"), ("oidc_issuer", "https://x.example/?a=1"), ("oidc_issuer", "notaurl"),
    ("oidc_name", "x" * 65), ("oidc_name", "a\nb"), ("ai_model", 5), ("ai_global_key", "has space inside it"),
    ("ai_global_key", 12345), ("nope", "x"), ("SECRET_KEY", "x"), ("secret_key", "x"), ("DB_PATH", "/tmp/x"),
    ("public_url", "https://x"),
])
def test_validate_rejects(key, value):
    with pytest.raises(config.ConfigError):
        config.validate(key, value)


def test_validation_errors_never_echo_secret():
    for value in ("bad secret " + SECRET, SECRET + "\x00tail", SECRET * 40):
        with pytest.raises(config.ConfigError) as exc:
            config.validate("ai_global_key", value)
        assert SECRET not in str(exc.value)


# ---------------------------------------------------------------- migration

def test_migration_on_old_database(monkeypatch, tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT,"
        " password_hash TEXT, oidc_sub TEXT UNIQUE, email TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);"
        "INSERT INTO users(id, username) VALUES (3, 'later'), (2, 'first');"
        "CREATE TABLE ai_usage(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), at TEXT NOT NULL,"
        " input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO ai_usage(user_id, at) VALUES (2, '2026-01-01T00:00:00');")
    old.commit()
    old.close()
    monkeypatch.setenv("DB_PATH", str(path))
    for _ in range(2):  # idempotent
        with db.conn() as c:
            db.init_shared(c)
            for module in (config, auth, ai, admin):
                module.init(c)
    with db.conn() as c:
        rows = c.execute("SELECT username, is_admin, disabled, use_global_ai, session_version FROM users "
                         "ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [("first", 0, 0, 1, 0), ("later", 0, 0, 1, 0)]
        assert c.execute("SELECT key_source FROM ai_usage").fetchone()[0] == "global"
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"app_config", "user_secrets", "user_ai", "admin_log"} <= tables
    auth.bootstrap_admin()  # no admin yet: the lowest id becomes one
    with db.conn() as c:
        assert [r[0] for r in c.execute("SELECT username FROM users WHERE is_admin=1")] == ["first"]
