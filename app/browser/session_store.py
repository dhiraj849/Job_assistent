"""Encrypted storage for the Naukri login session (Playwright storage_state).

The state holds session cookies, i.e. full access to the Naukri account,
so it is encrypted at rest with Fernet and its values are never logged.
"""

import json
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = structlog.get_logger(__name__)


class SessionStateError(Exception):
    """Missing key, missing file or wrong key. Messages never contain secrets."""


def _fernet() -> Fernet:
    if settings.NAUKRI_STATE_KEY is None:
        raise SessionStateError(
            "NAUKRI_STATE_KEY is not set. Generate one (see docs/09) and add it to .env."
        )
    try:
        return Fernet(settings.NAUKRI_STATE_KEY.get_secret_value().encode())
    except ValueError:
        raise SessionStateError("NAUKRI_STATE_KEY is not a valid Fernet key.") from None


def check_key() -> None:
    """Fail fast (before a manual login) if the encryption key is missing or invalid."""
    _fernet()


def _summary(state: dict) -> dict:
    # Safe to log: counts and domains only, never cookie names or values.
    return {
        "cookies": len(state.get("cookies", [])),
        "domains": sorted({c.get("domain", "") for c in state.get("cookies", [])}),
        "origins": len(state.get("origins", [])),
    }


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or settings.NAUKRI_STATE_PATH
    token = _fernet().encrypt(json.dumps(state).encode())

    # Owner-only folder and file: other local users can't read the session.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(token)
    path.chmod(0o600)

    logger.info("session_state_saved", path=str(path), **_summary(state))


def load_state(path: Path | None = None) -> dict:
    path = path or settings.NAUKRI_STATE_PATH
    if not path.exists():
        raise SessionStateError(
            f"No saved session at {path}. Run: uv run python -m scripts.naukri_login"
        )

    try:
        state = json.loads(_fernet().decrypt(path.read_bytes()))
    except InvalidToken:
        raise SessionStateError(
            f"Cannot decrypt {path}: wrong NAUKRI_STATE_KEY or corrupted file. "
            "Log in again with scripts.naukri_login."
        ) from None

    logger.info("session_state_loaded", path=str(path), **_summary(state))
    return state
