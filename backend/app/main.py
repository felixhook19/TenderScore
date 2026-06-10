"""FastAPI application factory.

M1 scope: tenancy, authentication and the audit spine. Routers for
ingestion, framework, scoring, moderation and documents arrive in M2
onwards per `docs/architecture.md` Part I.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.audit.middleware import AuditCompletenessMiddleware
from app.audit.router import router as audit_router
from app.auth.admin_router import router as admin_router
from app.auth.deps import MissingAuditEventError
from app.auth.router import router as auth_router
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
    app.add_middleware(AuditCompletenessMiddleware)

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
    return app


app = create_app()
