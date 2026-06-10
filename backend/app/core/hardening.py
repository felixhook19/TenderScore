"""Pre-pilot hardening: rate limiting and log scrubbing (M10).

The rate limiter is an in-process sliding window applied to the
authentication endpoints — enough for a single-instance pilot; replace
with a shared store when the deployment becomes multi-instance (P4).
"""

import logging
import re
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

RATE_LIMITED_PATHS = ("/auth/login", "/auth/totp")


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter on authentication endpoints, per client."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path not in RATE_LIMITED_PATHS:
            return await call_next(request)

        settings = get_settings()
        window = settings.auth_rate_limit_window_seconds
        limit = settings.auth_rate_limit_attempts
        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.url.path}"

        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Too many authentication attempts. Wait a minute and try "
                        "again."
                    )
                },
                headers={"Retry-After": str(window)},
            )
        hits.append(now)
        return await call_next(request)


_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_TOKENISH = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


class ScrubbingFilter(logging.Filter):
    """Redacts bearer tokens, emails and long token-like strings from logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        scrubbed = _BEARER.sub("Bearer [redacted]", message)
        scrubbed = _EMAIL.sub("[email redacted]", scrubbed)
        scrubbed = _TOKENISH.sub("[token redacted]", scrubbed)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_scrubbing() -> None:
    """Attach the scrubbing filter to the root logger's handlers and the
    access loggers uvicorn uses."""
    scrubber = ScrubbingFilter()
    for name in ("", "uvicorn.access", "uvicorn.error", "tenderscore.worker"):
        logging.getLogger(name).addFilter(scrubber)
