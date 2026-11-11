"""Test isolation: every test gets its own database and a clean configuration environment,
so a developer's real .env values or data/macrolog.db never leak into a test."""
import pytest

from app import config

CLEARED = [s.env for s in config.MANAGED.values()] + ["ADMIN_USER", "ADMIN_PASSWORD", "PUBLIC_URL",
                                                      "TRUST_PROXY", "COOKIE_SECURE"]
TEST_SECRET_KEY = "test-secret-key-0123456789-abcdefghijklmnop"


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    for name in CLEARED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "isolated.db"))
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    config._warned.clear()

