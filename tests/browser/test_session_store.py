import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.browser import session_store
from app.browser.session_store import SessionStateError, check_key, load_state, save_state
from app.config import settings

STATE = {
    "cookies": [{"name": "nauk_at", "value": "super-secret-cookie", "domain": ".naukri.com"}],
    "origins": [],
}


@pytest.fixture
def key(monkeypatch):
    """A throwaway Fernet key, so tests never touch the real one."""
    value = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "NAUKRI_STATE_KEY", SecretStr(value))
    return value


def test_round_trip_returns_same_state(tmp_path, key):
    path = tmp_path / "secrets" / "state.enc"

    save_state(STATE, path)

    assert load_state(path) == STATE


def test_file_is_encrypted_and_owner_only(tmp_path, key):
    path = tmp_path / "secrets" / "state.enc"

    save_state(STATE, path)

    assert b"super-secret-cookie" not in path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600


def test_wrong_key_gives_clear_error(tmp_path, key, monkeypatch):
    path = tmp_path / "state.enc"
    save_state(STATE, path)

    monkeypatch.setattr(settings, "NAUKRI_STATE_KEY", SecretStr(Fernet.generate_key().decode()))

    with pytest.raises(SessionStateError, match="Cannot decrypt"):
        load_state(path)


def test_missing_key_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_STATE_KEY", None)

    with pytest.raises(SessionStateError, match="NAUKRI_STATE_KEY is not set"):
        save_state(STATE, tmp_path / "state.enc")


def test_check_key_fails_fast_without_key(monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_STATE_KEY", None)

    with pytest.raises(SessionStateError, match="NAUKRI_STATE_KEY is not set"):
        check_key()


def test_check_key_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_STATE_KEY", SecretStr("not-a-fernet-key"))

    with pytest.raises(SessionStateError, match="not a valid Fernet key"):
        check_key()


def test_missing_file_gives_clear_error(tmp_path, key):
    with pytest.raises(SessionStateError, match="No saved session"):
        load_state(tmp_path / "missing.enc")


def test_log_summary_has_no_cookie_values():
    summary = session_store._summary(STATE)

    assert summary == {"cookies": 1, "domains": [".naukri.com"], "origins": 0}
    assert "super-secret-cookie" not in str(summary)
