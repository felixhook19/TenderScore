"""FastAPI application factory.

Startup runs the provider safety assertions (no-training, residency) and
reconciles the prompt registry — a changed prompt artefact without a
version bump fails startup outright.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.anonymisation.router import router as anonymisation_router
from app.audit.middleware import AuditCompletenessMiddleware
from app.audit.router import router as audit_router
from app.auth.admin_router import router as admin_router
from app.auth.deps import MissingAuditEventError
from app.auth.router import router as auth_router
from app.compliance.router import router as compliance_router
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.hardening import AuthRateLimitMiddleware, install_log_scrubbing
from app.documents.router import router as documents_router
from app.framework.router import router as framework_router
from app.ingestion.router import router as ingestion_router
from app.llm_gateway.registry import reconcile
from app.llm_gateway.safety import assert_provider_safety
from app.moderation.router import router as moderation_router
from app.scoring.router import router as scoring_router


class HealthResponse(BaseModel):
    """Health check payload."""

    status: str
    service: str
    environment: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    assert_provider_safety(get_settings())
    install_log_scrubbing()
    session = get_session_factory()()
    try:
        reconcile(session)
    finally:
        session.close()
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="AI scores, humans moderate, AI documents.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(AuditCompletenessMiddleware)
    app.add_middleware(AuthRateLimitMiddleware)

    @app.exception_handler(MissingAuditEventError)
    async def _missing_audit_event(
        request: Request, exc: MissingAuditEventError
    ) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            environment=settings.environment,
        )

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(audit_router)
    app.include_router(framework_router)
    app.include_router(ingestion_router)
    app.include_router(compliance_router)
    app.include_router(scoring_router)
    app.include_router(moderation_router)
    app.include_router(anonymisation_router)
    app.include_router(documents_router)
    return app


app = create_app()
