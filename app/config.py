from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # .env is shared with docker-compose (e.g. TEMPORAL_DB_*), so ignore
    # variables the app itself does not use instead of failing on them.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Job search
    JOB_SEARCH_KEYWORD: str = "Python Backend Engineer"

    JOB_SEARCH_LOCATION: str = "Noida"

    MAX_MATCH_JOBS: int = 5

    # Logging
    LOG_LEVEL: str = "INFO"

    LOG_FORMAT: Literal["console", "json"] = "console"

    # Candidate profile
    PROFILE_PATH: Path = Path("profile.yaml")

    # Standard answers for apply questions (notice period, CTC, skill years)
    ANSWERS_PATH: Path = Path("answers.yaml")

    # Apply safety rails. dry_run never opens a browser; switch to "live"
    # only on purpose. The cap protects the Naukri account from looking
    # like a bot (and me from mass-applying by mistake).
    APPLY_MODE: Literal["dry_run", "live"] = "dry_run"

    MAX_APPLIES_PER_DAY: int = Field(default=10, ge=1)

    # Browser
    BROWSER_HEADLESS: bool = False

    BROWSER_TIMEOUT_MS: int = 20000

    DETAIL_PAGE_DELAY_SECONDS: float = 3.0

    # Extra random 0..N seconds on top of the delay: a fixed gap between
    # requests is an easy bot signal.
    DETAIL_PAGE_JITTER_SECONDS: float = Field(default=2.0, ge=0)

    # Naukri login session (cookies + localStorage), encrypted at rest.
    # Generate a key: uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    NAUKRI_STATE_KEY: SecretStr | None = None

    NAUKRI_STATE_PATH: Path = Path("secrets/naukri_state.enc")

    # Database
    POSTGRES_USER: str = "job_agent"

    POSTGRES_PASSWORD: SecretStr = SecretStr("")

    POSTGRES_DB: str = "job_agent"

    POSTGRES_HOST: str = "localhost"

    POSTGRES_PORT: int = 5433

    # Vector database
    QDRANT_URL: str = "http://localhost:6333"

    # Temporal
    TEMPORAL_ADDRESS: str = "localhost:7233"

    TEMPORAL_NAMESPACE: str = "default"

    TEMPORAL_TASK_QUEUE: str = "job-agent"

    # X (Twitter) API credentials, used by the MCP server experiment
    X_CLIENT_ID: str | None = None

    X_CLIENT_SECRET: SecretStr | None = None


settings = Settings()