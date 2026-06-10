"""Application configuration.

All settings come from environment variables (see `.env.example` at the
repository root). No secrets are ever committed; no provider endpoints are
hard-coded — inference residency is a deployment constraint and stays
configurable (CLAUDE.md, rule on LLM usage).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-derived application settings."""

    model_config = SettingsConfigDict(env_prefix="TENDERSCORE_", env_file=".env", extra="ignore")

    app_name: str = "TenderScore"
    environment: str = "development"  # development | test | production

    database_url: str = "postgresql+psycopg://tenderscore:tenderscore@localhost:5432/tenderscore"

    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_bucket: str = "tenderscore-dev"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
