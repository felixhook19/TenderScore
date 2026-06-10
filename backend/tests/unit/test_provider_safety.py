"""Provider safety assertions: no-training and residency are not optional."""

import pytest

from app.core.config import Settings
from app.llm_gateway.safety import ProviderSafetyError, assert_provider_safety


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


def test_no_training_cannot_be_weakened() -> None:
    with pytest.raises(ProviderSafetyError, match="model training"):
        assert_provider_safety(_settings(provider_no_training=False))


def test_production_refuses_unlisted_endpoints() -> None:
    with pytest.raises(ProviderSafetyError, match="residency"):
        assert_provider_safety(
            _settings(
                environment="production",
                anthropic_base_url="https://api.example-not-allowed.com",
            )
        )


def test_development_configuration_passes() -> None:
    assert_provider_safety(_settings())
