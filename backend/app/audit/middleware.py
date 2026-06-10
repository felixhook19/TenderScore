"""Audit-completeness middleware.

Backstop enforcement of CLAUDE.md rule 1: a state-changing request that
completes successfully without emitting at least one audit event is a
defect, and the middleware refuses to present it as a success. The primary,
preventive check lives in the database-session dependency (which rolls the
transaction back before commit); this layer catches any handler that writes
state outside that dependency.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

AUDIT_COUNT_STATE_KEY = "audit_event_count"


class AuditCompletenessMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        setattr(request.state, AUDIT_COUNT_STATE_KEY, 0)
        response = await call_next(request)
        if (
            request.method in MUTATING_METHODS
            and 200 <= response.status_code < 300
            and getattr(request.state, AUDIT_COUNT_STATE_KEY, 0) == 0
        ):
            return JSONResponse(
                status_code=500,
                content={
                    "detail": (
                        "This state-changing request completed without recording an "
                        "audit event. The request has been reported as a defect; no "
                        "result is available."
                    )
                },
            )
        return response


def increment_audit_count(request: Request) -> None:
    """Recorders bound to a request call this on every event."""
    current = getattr(request.state, AUDIT_COUNT_STATE_KEY, 0)
    setattr(request.state, AUDIT_COUNT_STATE_KEY, current + 1)


def audit_count(request: Request) -> int:
    return int(getattr(request.state, AUDIT_COUNT_STATE_KEY, 0))
