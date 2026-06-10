"""Read-only audit endpoints: event listing and chain verification."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.verifier import verify_scope
from app.auth.deps import CurrentUser, get_db, require_roles
from app.auth.roles import Role

router = APIRouter(prefix="/audit", tags=["audit"])

_audit_reader = require_roles(Role.ADMIN, Role.OBSERVER_AUDITOR)


class AuditEventOut(BaseModel):
    id: int
    tenant_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_type: str
    action: str
    entity_type: str
    entity_id: str
    before_hash: str | None
    after_hash: str | None
    prompt_id: str | None
    prompt_version: str | None
    model_version: str | None
    occurred_at: datetime
    prev_event_hash: str
    event_hash: str


class ChainReportOut(BaseModel):
    scope: str
    event_count: int
    valid: bool
    first_invalid_event_id: int | None
    detail: str | None


@router.get("/events", response_model=list[AuditEventOut])
def list_events(
    user: Annotated[CurrentUser, Depends(_audit_reader)],
    db: Annotated[Session, Depends(get_db)],
    entity_type: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventOut]:
    """List audit events for the caller's tenant, newest first."""
    query = select(AuditEvent).where(AuditEvent.tenant_id == user.tenant_id)
    if entity_type is not None:
        query = query.where(AuditEvent.entity_type == entity_type)
    if action is not None:
        query = query.where(AuditEvent.action == action)
    query = query.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)
    events = db.scalars(query).all()
    return [AuditEventOut.model_validate(event, from_attributes=True) for event in events]


@router.get("/verify", response_model=ChainReportOut)
def verify_chain(
    user: Annotated[CurrentUser, Depends(_audit_reader)],
    db: Annotated[Session, Depends(get_db)],
) -> ChainReportOut:
    """Verify the caller's tenant chain end to end and report the outcome."""
    report = verify_scope(db, user.tenant_id)
    return ChainReportOut(
        scope=report.scope,
        event_count=report.event_count,
        valid=report.valid,
        first_invalid_event_id=report.first_invalid_event_id,
        detail=report.detail,
    )
