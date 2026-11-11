import pytest

from app import main


def test_short_secret_key_refuses_to_start(monkeypatch):
    for value in (None, "", "x" * 31):
        if value is None:
            monkeypatch.delenv("SECRET_KEY", raising=False)
        else:
            monkeypatch.setenv("SECRET_KEY", value)
        with pytest.raises(RuntimeError, match="at least 32 characters"):
            main.create_app()


def test_long_secret_key_starts(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    assert main.create_app().title == "Macrolog"
