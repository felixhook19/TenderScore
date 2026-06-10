"""Provider adapters. No module outside the gateway calls a provider SDK."""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import anthropic

from app.core.config import get_settings


@dataclass(frozen=True)
class AdapterResponse:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class ProviderAdapter(Protocol):
    """The provider seam: one completion, whole-response (no streaming in
    scoring paths — whole-response validation is required)."""

    def complete(
        self,
        *,
        model_version: str,
        system: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
    ) -> AdapterResponse: ...


class AnthropicAdapter:
    """Anthropic API adapter.

    The endpoint comes from configuration (UK/EEA residency is a deployment
    constraint — never hard-coded). API usage is not used for model
    training; the configuration assertion in `app.llm_gateway.safety`
    refuses to start if that guarantee is weakened.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(base_url=settings.anthropic_base_url)

    def complete(
        self,
        *,
        model_version: str,
        system: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
    ) -> AdapterResponse:
        started = time.monotonic()
        response = self._client.messages.create(
            model=model_version,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return AdapterResponse(
            text=text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            latency_ms=latency_ms,
        )


class DeterministicFakeAdapter:
    """Deterministic adapter for tests and offline development.

    Responses are produced by a caller-supplied function of the request, so
    test suites (regression oracle, red-team corpus) control outputs exactly
    and replays are bit-identical.
    """

    def __init__(
        self, respond: Callable[[str, str], str] | None = None
    ) -> None:
        self._respond = respond
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model_version: str,
        system: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
    ) -> AdapterResponse:
        self.calls.append(
            {
                "model_version": model_version,
                "system": system,
                "user_content": user_content,
                "temperature": temperature,
            }
        )
        if self._respond is not None:
            text = self._respond(system, user_content)
        else:
            digest = hashlib.sha256((system + user_content).encode("utf-8")).hexdigest()
            text = f'{{"echo": "{digest}"}}'
        return AdapterResponse(
            text=text,
            tokens_in=len(system.split()) + len(user_content.split()),
            tokens_out=len(text.split()),
            latency_ms=0,
        )
