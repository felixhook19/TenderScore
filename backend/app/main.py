"""FastAPI application factory.

M0 scope: app factory and health endpoint only. Business modules (audit,
auth, tenancy, ingestion, framework, compliance, anonymisation, llm_gateway,
scoring, moderation, documents) are scaffolded as packages and built in
M1 to M8 per `docs/architecture.md` Part I.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import get_settings


class HealthResponse(BaseModel):
    """Health check payload."""

    status: str
    service: str
    environment: str


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="AI scores, humans moderate, AI documents.",
        version="0.1.0",
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            environment=settings.environment,
        )

    return app


app = create_app()
