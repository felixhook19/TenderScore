"""Audit event recorder.

Every state change goes through here. The recorder appends to the per-scope
hash chain (one chain per tenant, plus one platform chain for events with no
tenant), serialising chain extension with a transaction-scoped advisory lock
so concurrent writers cannot fork a chain.
"""

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, select, text
from sqlalchemy.orm import Session

from app.audit.hashing import GENESIS_HASH, compute_event_hash, event_payload
from app.audit.models import AuditEvent


def chain_scope_key(tenant_id: uuid.UUID | None) -> str:
    """The chain a tenant's events belong to; platform events chain separately."""
    return f"tenant:{tenant_id}" if tenant_id is not None else "platform"


def _advisory_lock_key(scope_key: str) -> int:
    digest = hashlib.sha256(scope_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class AuditRecorder:
    """Appends audit events for one actor within one database session.

    The events join the caller's transaction: a rolled-back state change
    rolls its events back with it, and a committed one cannot commit without
    them.
    """

    def __init__(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        actor_type: str = "user",
        on_record: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id
        self._actor_type = actor_type
        self._on_record = on_record
        self.count = 0

    @property
    def tenant_id(self) -> uuid.UUID | None:
        return self._tenant_id

    def record(
        self,
        action: str,
        *,
        entity_type: str,
        entity_id: str,
        before_hash: str | None = None,
        after_hash: str | None = None,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
        model_version: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> AuditEvent:
        """Append one event to the chain and return it (flushed, not committed)."""
        scope_tenant_id = tenant_id if tenant_id is not None else self._tenant_id
        scope = chain_scope_key(scope_tenant_id)

        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _advisory_lock_key(scope)}
        )

        scope_filter: ColumnElement[bool] = (
            AuditEvent.tenant_id.is_(None)
            if scope_tenant_id is None
            else AuditEvent.tenant_id == scope_tenant_id
        )
        prev_event_hash = self._session.scalar(
            select(AuditEvent.event_hash)
            .where(scope_filter)
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
        if prev_event_hash is None:
            prev_event_hash = GENESIS_HASH

        occurred_at = datetime.now(UTC)
        payload = event_payload(
            tenant_id=scope_tenant_id,
            actor_id=self._actor_id,
            actor_type=self._actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_hash=before_hash,
            after_hash=after_hash,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model_version=model_version,
            occurred_at=occurred_at,
        )
        event = AuditEvent(
            tenant_id=scope_tenant_id,
            actor_id=self._actor_id,
            actor_type=self._actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_hash=before_hash,
            after_hash=after_hash,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model_version=model_version,
            occurred_at=occurred_at,
            prev_event_hash=prev_event_hash,
            event_hash=compute_event_hash(prev_event_hash, payload),
        )
        self._session.add(event)
        self._session.flush()
        self.count += 1
        if self._on_record is not None:
            self._on_record()
        return event
