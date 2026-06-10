"""Scoring job handler: executes one run (one criterion x one bidder)."""

import uuid

from sqlalchemy import select

from app.jobs.runner import JobContext, register_handler
from app.llm_gateway.adapters import AnthropicAdapter, ProviderAdapter
from app.llm_gateway.gateway import LLMGateway
from app.llm_gateway.registry import resolve
from app.scoring.engine import SCORE_PROMPT_ID, execute_run
from app.scoring.models import ScoringRun

SCORING_JOB_TYPE = "scoring.run"

# Test suites and offline development swap the adapter here; production
# uses the Anthropic adapter. Only the gateway ever touches the adapter.
_adapter_instance: ProviderAdapter | None = None


def set_adapter(adapter: ProviderAdapter | None) -> None:
    global _adapter_instance
    _adapter_instance = adapter


def _adapter() -> ProviderAdapter:
    if _adapter_instance is not None:
        return _adapter_instance
    return AnthropicAdapter()


def handle_scoring_run(context: JobContext) -> None:
    run_id = uuid.UUID(str(context.payload["run_id"]))
    run = context.session.scalar(select(ScoringRun).where(ScoringRun.id == run_id))
    if run is None:
        raise ValueError(f"Scoring run {run_id} was not found.")
    if run.status == "blocked":
        return
    prompt = resolve(context.session, SCORE_PROMPT_ID)
    gateway = LLMGateway(_adapter())
    execute_run(context.session, context.recorder, gateway, prompt, run=run)


def register() -> None:
    register_handler(SCORING_JOB_TYPE, handle_scoring_run)
