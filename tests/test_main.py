import pytest

from app import main


def test_short_secret_key_refuses_to_start(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 31)
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        main.create_app()


@pytest.mark.parametrize("unset", [True, False])
def test_missing_secret_key_is_generated_once_and_reused(monkeypatch, tmp_path, unset):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "macrolog.db"))
    if unset:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", "")
    main.create_app()
    first = main.os.environ["SECRET_KEY"]
    path = tmp_path / "data" / "secret_key"
    assert len(first) >= 32 and path.read_text() == first
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    monkeypatch.delenv("SECRET_KEY")
    main.create_app()
    assert main.os.environ["SECRET_KEY"] == first


def test_env_secret_key_wins_over_stored_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "macrolog.db"))
    (tmp_path / "secret_key").write_text("f" * 40)
    monkeypatch.setenv("SECRET_KEY", "e" * 40)
    main.create_app()
    assert main.os.environ["SECRET_KEY"] == "e" * 40


def test_damaged_stored_secret_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "macrolog.db"))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    (tmp_path / "secret_key").write_text("short")
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        main.create_app()


def test_long_secret_key_starts(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    assert main.create_app().title == "Macrolog"
