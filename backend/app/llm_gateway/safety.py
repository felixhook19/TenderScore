"""Provider safety assertions, checked at startup.

- No training on customer data: the configuration assertion cannot be
  weakened in any environment (CLAUDE.md rule 8).
- Residency: provider endpoints are configuration; a production
  environment refuses endpoints not on the UK/EEA list.
"""

from app.core.config import Settings

# [[ASSUMED]] Endpoint allowlist for production residency. Confirm the
# UK/EEA inference residency options with the provider before any pilot.
UK_EEA_ENDPOINT_PREFIXES = (
    "https://api.eu.anthropic.com",
    "https://api.anthropic.com",  # placeholder until residency is confirmed
)


class ProviderSafetyError(Exception):
    """A provider safety guarantee is misconfigured; refuse to start."""


def assert_provider_safety(settings: Settings) -> None:
    if not settings.provider_no_training:
        raise ProviderSafetyError(
            "provider_no_training must be true: no customer data is ever used "
            "for model training. This assertion cannot be weakened."
        )
    if settings.environment == "production" and not settings.anthropic_base_url.startswith(
        UK_EEA_ENDPOINT_PREFIXES
    ):
        raise ProviderSafetyError(
            "The configured provider endpoint is not on the UK/EEA residency "
            "allowlist; refusing to start in production."
        )
