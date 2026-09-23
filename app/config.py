from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env")

    JOB_SEARCH_KEYWORD: str = "Python Backend Engineer"

    JOB_SEARCH_LOCATION: str = "Noida"

    MAX_MATCH_JOBS: int = 5

    LOG_LEVEL: str = "INFO"

    LOG_FORMAT: Literal["console", "json"] = "console"

    # X (Twitter) API credentials, used by the MCP server experiment
    X_CLIENT_ID: str | None = None

    X_CLIENT_SECRET: SecretStr | None = None


settings = Settings()