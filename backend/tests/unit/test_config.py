"""Configuration tests."""

from app.core.config import Settings


def _settings_without_env_file() -> Settings:
    # _env_file is a runtime-only pydantic-settings init argument.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults_are_development_grade() -> None:
    settings = _settings_without_env_file()
    assert settings.environment == "development"
    assert settings.app_name == "TenderScore"


def test_no_secrets_in_defaults() -> None:
    settings = _settings_without_env_file()
    assert settings.object_storage_access_key == ""
    assert settings.object_storage_secret_key == ""
