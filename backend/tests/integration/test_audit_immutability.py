"""M1 exit criterion: UPDATE/DELETE on audit_events is rejected by the
database itself — by revoked privileges first, and by the trigger even when
privileges are granted back."""

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder


@pytest.fixture
def seeded_event_id(db_session: Session) -> Iterator[int]:
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    event = recorder.record("test.seeded", entity_type="test", entity_id="immutability")
    db_session.commit()
    yield event.id


def test_update_is_rejected(db_session: Session, seeded_event_id: int) -> None:
    with pytest.raises(DatabaseError, match=r"permission denied|append-only"):
        db_session.execute(
            text("UPDATE platform.audit_events SET action = 'tampered' WHERE id = :id"),
            {"id": seeded_event_id},
        )
    db_session.rollback()


def test_delete_is_rejected(db_session: Session, seeded_event_id: int) -> None:
    with pytest.raises(DatabaseError, match=r"permission denied|append-only"):
        db_session.execute(
            text("DELETE FROM platform.audit_events WHERE id = :id"),
            {"id": seeded_event_id},
        )
    db_session.rollback()


def test_truncate_is_rejected(db_session: Session, seeded_event_id: int) -> None:
    with pytest.raises(DatabaseError, match=r"permission denied|append-only"):
        db_session.execute(text("TRUNCATE platform.audit_events"))
    db_session.rollback()


def test_trigger_blocks_even_with_privileges_granted_back(
    db_session: Session, seeded_event_id: int
) -> None:
    """The owner can re-grant privileges, but the trigger still refuses."""
    db_session.execute(
        text("GRANT UPDATE, DELETE ON platform.audit_events TO current_user")
    )
    try:
        with pytest.raises(DatabaseError, match="append-only"):
            db_session.execute(
                text("UPDATE platform.audit_events SET action = 'tampered' WHERE id = :id"),
                {"id": seeded_event_id},
            )
        db_session.rollback()
    finally:
        db_session.execute(
            text(
                "DO $$ BEGIN EXECUTE format("
                "'REVOKE UPDATE, DELETE ON platform.audit_events FROM %I', current_user"
                "); END $$"
            )
        )
        db_session.commit()
