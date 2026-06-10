"""Request-scoped dependencies: database sessions, current user, RBAC guards.

Two session dependencies exist:
- `get_db` — platform-schema work (auth, admin, audit reads).
- `get_tenant_db` — tenant-schema work; unqualified tables resolve to the
  authenticated user's tenant schema (ADR-003).

Both carry the preventive half of audit enforcement: a mutating request
whose transaction is about to commit with zero recorded audit events is
rolled back and refused. The middleware in `app.audit.middleware` is the
detection backstop.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.middleware import MUTATING_METHODS, audit_count, increment_audit_count
from app.audit.recorder import AuditRecorder
from app.auth.models import SessionToken, User, UserPrivilege, UserRole
from app.auth.provider import hash_token
from app.auth.roles import Role
from app.core.db import get_session_factory, tenant_session
from app.tenancy.models import Tenant

_bearer = HTTPBearer(auto_error=False)


class MissingAuditEventError(RuntimeError):
    """A state-changing request reached commit without an audit event."""


def _close_with_enforcement(session: Session, request: Request) -> None:
    """Commit the request transaction, refusing un-audited state changes."""
    if request.method in MUTATING_METHODS and audit_count(request) == 0:
        session.rollback()
        session.close()
        raise MissingAuditEventError(
            "This state-changing request reached commit without recording an audit "
            "event; the transaction has been rolled back. Emitting an audit event is "
            "not optional (CLAUDE.md rule 1)."
        )
    session.commit()
    session.close()


def get_db(request: Request) -> Iterator[Session]:
    """Platform-schema request transaction with audit enforcement."""
    session = get_session_factory()()
    try:
        yield session
    except BaseException:
        session.rollback()
        session.close()
        raise
    _close_with_enforcement(session, request)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_schema: str
    email: str
    display_name: str
    roles: frozenset[str]
    privileges: frozenset[str]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Resolve the session token to a user, in a dedicated read session."""
    unauthenticated = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthenticated

    db = get_session_factory()()
    try:
        token = db.scalar(
            select(SessionToken).where(
                SessionToken.token_hash == hash_token(credentials.credentials),
                SessionToken.status == "active",
            )
        )
        if token is None or token.expires_at <= datetime.now(UTC):
            raise unauthenticated

        user = db.get(User, token.user_id)
        if user is None or user.status != "active":
            raise unauthenticated

        schema = db.scalar(select(Tenant.schema_name).where(Tenant.id == user.tenant_id))
        if schema is None:
            raise unauthenticated

        roles = db.scalars(select(UserRole.role).where(UserRole.user_id == user.id)).all()
        privileges = db.scalars(
            select(UserPrivilege.privilege).where(UserPrivilege.user_id == user.id)
        ).all()
        return CurrentUser(
            id=user.id,
            tenant_id=user.tenant_id,
            tenant_schema=schema,
            email=user.email,
            display_name=user.display_name,
            roles=frozenset(roles),
            privileges=frozenset(privileges),
        )
    finally:
        db.close()


def get_tenant_db(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> Iterator[Session]:
    """Tenant-schema request transaction with audit enforcement."""
    session = tenant_session(user.tenant_schema)
    try:
        yield session
    except BaseException:
        session.rollback()
        session.close()
        raise
    _close_with_enforcement(session, request)


def require_roles(*allowed: Role) -> Callable[..., CurrentUser]:
    """Default-deny route guard: the caller must hold one of the given roles."""

    def dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if not user.roles.intersection({role.value for role in allowed}):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return dependency


def require_privilege(privilege: str) -> Callable[..., CurrentUser]:
    """Guard for distinct privileges (never implied by any role)."""

    def dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if privilege not in user.privileges:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires a privilege you have not been granted.",
            )
        return user

    return dependency


def get_recorder(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AuditRecorder:
    """An audit recorder bound to the platform request transaction."""
    return AuditRecorder(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_type="user",
        on_record=lambda: increment_audit_count(request),
    )


def get_tenant_recorder(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> AuditRecorder:
    """An audit recorder bound to the tenant request transaction."""
    return AuditRecorder(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_type="user",
        on_record=lambda: increment_audit_count(request),
    )
