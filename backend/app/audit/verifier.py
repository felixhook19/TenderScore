"""Hash-chain verifier.

Re-walks every chain from genesis, recomputing each event hash from the
stored columns. Any edit, deletion or forged insertion breaks the chain at
the point of tampering, whatever privileges the tamperer held.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.audit.hashing import GENESIS_HASH, compute_event_hash, event_payload
from app.audit.models import AuditEvent
from app.audit.recorder import chain_scope_key


@dataclass(frozen=True)
class ChainReport:
    """Verification outcome for one chain (one tenant, or the platform)."""

    scope: str
    event_count: int
    valid: bool
    first_invalid_event_id: int | None
    detail: str | None


def verify_scope(session: Session, tenant_id: uuid.UUID | None) -> ChainReport:
    """Verify one chain end to end."""
    scope = chain_scope_key(tenant_id)
    scope_filter: ColumnElement[bool] = (
        AuditEvent.tenant_id.is_(None)
        if tenant_id is None
        else AuditEvent.tenant_id == tenant_id
    )

    events = session.scalars(
        select(AuditEvent).where(scope_filter).order_by(AuditEvent.id)
    ).all()

    expected_prev = GENESIS_HASH
    for event in events:
        if event.prev_event_hash != expected_prev:
            return ChainReport(
                scope=scope,
                event_count=len(events),
                valid=False,
                first_invalid_event_id=event.id,
                detail="Previous-hash link does not match the preceding event.",
            )
        payload = event_payload(
            tenant_id=event.tenant_id,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            before_hash=event.before_hash,
            after_hash=event.after_hash,
            prompt_id=event.prompt_id,
            prompt_version=event.prompt_version,
            model_version=event.model_version,
            occurred_at=event.occurred_at,
        )
        recomputed = compute_event_hash(event.prev_event_hash, payload)
        if recomputed != event.event_hash:
            return ChainReport(
                scope=scope,
                event_count=len(events),
                valid=False,
                first_invalid_event_id=event.id,
                detail="Recorded event hash does not match the recomputed value.",
            )
        expected_prev = event.event_hash

    return ChainReport(
        scope=scope,
        event_count=len(events),
        valid=True,
        first_invalid_event_id=None,
        detail=None,
    )


def verify_all(session: Session) -> list[ChainReport]:
    """Verify every chain present in the store."""
    tenant_ids = session.scalars(select(AuditEvent.tenant_id).distinct()).all()
    reports = [verify_scope(session, tenant_id) for tenant_id in tenant_ids]
    return sorted(reports, key=lambda report: report.scope)
