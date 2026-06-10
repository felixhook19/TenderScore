"""M1 exit criterion: the chain verifier detects tampering.

Tampering here requires owner-level access plus deliberately disabling the
enforcement trigger — exactly the scenario the verifier exists to expose.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit.hashing import GENESIS_HASH
from app.audit.recorder import AuditRecorder
from app.audit.verifier import verify_scope


def _seed_chain(db_session: Session, tenant_id: uuid.UUID, events: int = 3) -> list[int]:
    recorder = AuditRecorder(
        db_session, tenant_id=tenant_id, actor_id=None, actor_type="system"
    )
    ids = [
        recorder.record(f"test.event_{n}", entity_type="test", entity_id=str(n)).id
        for n in range(events)
    ]
    db_session.commit()
    return ids


def test_untampered_chain_verifies(db_session: Session) -> None:
    tenant_id = uuid.uuid4()
    _seed_chain(db_session, tenant_id)
    report = verify_scope(db_session, tenant_id)
    assert report.valid
    assert report.event_count == 3
    assert report.first_invalid_event_id is None


def test_verifier_detects_a_rewritten_event(db_session: Session) -> None:
    tenant_id = uuid.uuid4()
    ids = _seed_chain(db_session, tenant_id)
    victim = ids[1]

    db_session.execute(
        text("GRANT UPDATE ON platform.audit_events TO current_user")
    )
    db_session.execute(
        text("ALTER TABLE platform.audit_events DISABLE TRIGGER audit_events_no_update_delete")
    )
    db_session.execute(
        text("UPDATE platform.audit_events SET action = 'tampered' WHERE id = :id"),
        {"id": victim},
    )
    db_session.execute(
        text("ALTER TABLE platform.audit_events ENABLE TRIGGER audit_events_no_update_delete")
    )
    db_session.execute(
        text(
            "DO $$ BEGIN EXECUTE format("
            "'REVOKE UPDATE ON platform.audit_events FROM %I', current_user"
            "); END $$"
        )
    )
    db_session.commit()

    report = verify_scope(db_session, tenant_id)
    assert not report.valid
    assert report.first_invalid_event_id == victim
    assert report.detail is not None and "Recorded event hash" in report.detail


def test_verifier_detects_a_forged_insertion(db_session: Session) -> None:
    tenant_id = uuid.uuid4()
    _seed_chain(db_session, tenant_id)

    db_session.execute(
        text(
            """
            INSERT INTO platform.audit_events
                (tenant_id, actor_type, action, entity_type, entity_id,
                 occurred_at, prev_event_hash, event_hash)
            VALUES
                (:tenant_id, 'system', 'test.forged', 'test', 'forged',
                 now(), :prev_hash, :event_hash)
            """
        ),
        {
            "tenant_id": tenant_id,
            "prev_hash": GENESIS_HASH,
            "event_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        },
    )
    db_session.commit()

    report = verify_scope(db_session, tenant_id)
    assert not report.valid
    assert report.detail is not None and "Previous-hash link" in report.detail


def test_chains_are_isolated_per_tenant(db_session: Session) -> None:
    """One tenant's events never link into another tenant's chain."""
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    _seed_chain(db_session, tenant_a)
    _seed_chain(db_session, tenant_b)
    assert verify_scope(db_session, tenant_a).valid
    assert verify_scope(db_session, tenant_b).valid
