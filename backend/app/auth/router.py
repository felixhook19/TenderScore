"""Authentication endpoints: login (password), TOTP verification, identity.

Failed attempts are audited in their own transaction (the request itself
fails with 401, so the request transaction rolls back), and successes are
audited in the request transaction like every other state change.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.hashing import state_hash
from app.audit.middleware import increment_audit_count
from app.audit.recorder import AuditRecorder
from app.auth.deps import CurrentUser, get_current_user, get_db
from app.auth.provider import AuthenticationError, get_identity_provider, hash_token
from app.core.db import get_session_factory

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    challenge_token: str
    expires_at: datetime
    detail: str


class TotpRequest(BaseModel):
    challenge_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)


class SessionResponse(BaseModel):
    session_token: str
    expires_at: datetime


class MeResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    display_name: str
    roles: list[str]
    privileges: list[str]


def _record_failure(error: AuthenticationError, action: str, fallback_entity_id: str) -> None:
    """Audit a failed authentication step in its own committed transaction."""
    session = get_session_factory()()
    try:
        user = error.user
        recorder = AuditRecorder(
            session,
            tenant_id=user.tenant_id if user is not None else None,
            actor_id=user.id if user is not None else None,
            actor_type="user" if user is not None else "system",
        )
        recorder.record(
            action,
            entity_type="user",
            entity_id=str(user.id) if user is not None else fallback_entity_id,
        )
        session.commit()
    finally:
        session.close()


def _is_locked_out(db: Session, email: str) -> bool:
    """Account lockout: too many recent failed attempts for this user."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func as sa_func

    from app.audit.models import AuditEvent
    from app.auth.models import User
    from app.core.config import get_settings

    settings = get_settings()
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        return False
    window_start = datetime.now(UTC) - timedelta(minutes=settings.lockout_window_minutes)
    failures = db.scalar(
        select(sa_func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action.in_(["auth.login.failed", "auth.totp.failed"]),
            AuditEvent.entity_id == str(user.id),
            AuditEvent.occurred_at >= window_start,
        )
    )
    return (failures or 0) >= settings.lockout_failed_attempts


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    if _is_locked_out(db, str(body.email)):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "This account is temporarily locked after repeated failed "
                "sign-in attempts. Try again later."
            ),
        )
    provider = get_identity_provider()
    try:
        challenge = provider.begin_authentication(db, str(body.email), body.password)
    except AuthenticationError as error:
        _record_failure(error, "auth.login.failed", state_hash({"email": str(body.email)}))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from error

    recorder = AuditRecorder(
        db,
        tenant_id=challenge.user.tenant_id,
        actor_id=challenge.user.id,
        actor_type="user",
        on_record=lambda: increment_audit_count(request),
    )
    recorder.record(
        "auth.login.password_verified",
        entity_type="user",
        entity_id=str(challenge.user.id),
    )
    return LoginResponse(
        challenge_token=challenge.challenge_token,
        expires_at=challenge.expires_at,
        detail="Enter the verification code from your authenticator app.",
    )


@router.post("/auth/totp", response_model=SessionResponse)
def verify_totp(
    body: TotpRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SessionResponse:
    provider = get_identity_provider()
    try:
        identity = provider.complete_authentication(db, body.challenge_token, body.code)
    except AuthenticationError as error:
        _record_failure(error, "auth.totp.failed", "unknown")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from error

    recorder = AuditRecorder(
        db,
        tenant_id=identity.user.tenant_id,
        actor_id=identity.user.id,
        actor_type="user",
        on_record=lambda: increment_audit_count(request),
    )
    recorder.record(
        "auth.login.succeeded",
        entity_type="user",
        entity_id=str(identity.user.id),
    )
    return SessionResponse(
        session_token=identity.session_token, expires_at=identity.expires_at
    )


class LogoutResponse(BaseModel):
    detail: str


@router.post("/auth/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LogoutResponse:
    """Revoke the presented session token (session hardening, M10)."""
    from app.auth.models import SessionToken

    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    session_row = db.scalar(
        select(SessionToken).where(SessionToken.token_hash == hash_token(token))
    )
    if session_row is not None:
        session_row.status = "revoked"
        db.flush()
    recorder = AuditRecorder(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_type="user",
        on_record=lambda: increment_audit_count(request),
    )
    recorder.record("auth.logout", entity_type="user", entity_id=str(user.id))
    return LogoutResponse(detail="You have been signed out.")


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=sorted(user.roles),
        privileges=sorted(user.privileges),
    )
