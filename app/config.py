from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env")

    # Job search
    JOB_SEARCH_KEYWORD: str = "Python Backend Engineer"

    JOB_SEARCH_LOCATION: str = "Noida"

    MAX_MATCH_JOBS: int = 5

    # Logging
    LOG_LEVEL: str = "INFO"

    LOG_FORMAT: Literal["console", "json"] = "console"

    # Candidate profile
    PROFILE_PATH: Path = Path("profile.yaml")

    # Browser
    BROWSER_HEADLESS: bool = False

    BROWSER_TIMEOUT_MS: int = 20000

    DETAIL_PAGE_DELAY_SECONDS: float = 3.0

    # Database
    POSTGRES_USER: str = "job_agent"

    POSTGRES_PASSWORD: SecretStr = SecretStr("")

    POSTGRES_DB: str = "job_agent"

    POSTGRES_HOST: str = "localhost"

    POSTGRES_PORT: int = 5433

    # Vector database
    QDRANT_URL: str = "http://localhost:6333"

    # X (Twitter) API credentials, used by the MCP server experiment
    X_CLIENT_ID: str | None = None

    X_CLIENT_SECRET: SecretStr | None = None


settings = Settings()