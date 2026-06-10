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

    platform_schema: str = "platform"

    # [[ASSUMED]] Default model pinned at framework lock. Confirm the exact
    # model string and UK/EEA inference residency before any pilot — this is
    # the single configuration location for it (handover section 5).
    pinned_model_version_default: str = "claude-sonnet-4-6"
    # Endpoint stays configurable; never hard-code (UK/EEA residency).
    anthropic_base_url: str = "https://api.anthropic.com"
    # Providers must never train on customer data (CLAUDE.md rule 8).
    # Asserted at startup; weakening this in configuration is refused.
    provider_no_training: bool = True

    # Criteria at or above this weighting get 5 scoring passes. [[ASSUMED]]
    high_weight_threshold_pct: float = 15.0
    scoring_passes_default: int = 3
    scoring_passes_high_weight: int = 5
    # Lexical-overlap threshold for descriptor vocabulary checks (flag, not
    # fail, in v1 — tune with calibration data).
    descriptor_vocabulary_overlap_threshold: float = 0.12

    session_ttl_minutes: int = 720
    totp_challenge_ttl_minutes: int = 5
    bcrypt_rounds: int = 12

    # Authentication hardening (M10).
    auth_rate_limit_attempts: int = 30
    auth_rate_limit_window_seconds: int = 60
    lockout_failed_attempts: int = 5
    lockout_window_minutes: int = 15


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
