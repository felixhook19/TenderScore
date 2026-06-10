"""M3 exit criteria: lock immutability and hash reproducibility."""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.recorder import AuditRecorder
from app.core.db import tenant_session
from app.framework.models import Procurement
from app.framework.service import (
    FrameworkLockedError,
    add_criterion,
    add_lot,
    compute_lock_hash,
    create_procurement,
    lock_framework,
)
from tests.conftest import TenantFactory


@pytest.fixture
def tenant_db(
    make_tenant_with_admin: TenantFactory,
) -> Iterator[tuple[Session, AuditRecorder, uuid.UUID]]:
    provisioned = make_tenant_with_admin()
    from app.core.db import get_session_factory
    from app.tenancy.models import Tenant

    lookup = get_session_factory()()
    try:
        tenant = lookup.get(Tenant, provisioned.tenant.id)
        assert tenant is not None
        schema = tenant.schema_name
    finally:
        lookup.close()
    session = tenant_session(schema)
    recorder = AuditRecorder(
        session, tenant_id=provisioned.tenant.id, actor_id=None, actor_type="system"
    )
    try:
        yield session, recorder, provisioned.tenant.id
    finally:
        session.rollback()
        session.close()


def _minimal_procurement(session: Session, recorder: AuditRecorder) -> "Procurement":
    procurement = create_procurement(
        session,
        recorder,
        title="Test Procurement",
        reference=f"T-{uuid.uuid4().hex[:8]}",
        regime="PA23",
    )
    add_criterion(
        session,
        recorder,
        procurement=procurement,
        ref="Q1",
        title="Quality",
        weighting_pct=Decimal("60"),
        descriptors=[(0, "Poor", "Fails."), (3, "Good", "Meets the requirement.")],
    )
    return procurement


def test_locked_framework_reproduces_its_hash(
    tenant_db: tuple[Session, AuditRecorder, uuid.UUID],
) -> None:
    session, recorder, _ = tenant_db
    procurement = _minimal_procurement(session, recorder)
    lock_event = lock_framework(
        session, recorder, procurement=procurement, locked_by=None
    )
    session.commit()
    recomputed = compute_lock_hash(session, procurement, lock_event.model_version)
    assert recomputed == lock_event.lock_hash
    assert procurement.framework_lock_hash == lock_event.lock_hash
    assert procurement.pinned_model_version == lock_event.model_version


def test_post_lock_edits_are_rejected(
    tenant_db: tuple[Session, AuditRecorder, uuid.UUID],
) -> None:
    session, recorder, _ = tenant_db
    procurement = _minimal_procurement(session, recorder)
    lock_framework(session, recorder, procurement=procurement, locked_by=None)
    session.commit()

    with pytest.raises(FrameworkLockedError):
        add_lot(session, recorder, procurement=procurement, lot_number=1, title="Late lot")
    session.rollback()
    with pytest.raises(FrameworkLockedError):
        add_criterion(
            session,
            recorder,
            procurement=procurement,
            ref="Q9",
            title="Late criterion",
            weighting_pct=Decimal("5"),
        )
    session.rollback()
    with pytest.raises(FrameworkLockedError):
        lock_framework(session, recorder, procurement=procurement, locked_by=None)
    session.rollback()


def test_rejected_post_lock_edit_is_audited_via_api(
    client: "object", make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    from fastapi.testclient import TestClient

    from tests.conftest import bearer, login

    assert isinstance(client, TestClient)
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)
    headers = bearer(token)

    created = client.post(
        "/procurements",
        headers=headers,
        json={"title": "API Lock Test", "reference": f"API-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    procurement_id = created.json()["id"]
    criterion = client.post(
        f"/procurements/{procurement_id}/criteria",
        headers=headers,
        json={
            "ref": "Q1",
            "title": "Quality",
            "weighting_pct": "60",
            "descriptors": [
                {"band": 0, "label": "Poor", "descriptor_text": "Fails."},
                {"band": 3, "label": "Good", "descriptor_text": "Meets."},
            ],
        },
    )
    assert criterion.status_code == 201, criterion.text
    locked = client.post(
        f"/procurements/{procurement_id}/framework/lock", headers=headers
    )
    assert locked.status_code == 200, locked.text

    refused = client.post(
        f"/procurements/{procurement_id}/lots",
        headers=headers,
        json={"lot_number": 1, "title": "Too late"},
    )
    assert refused.status_code == 409

    db_session.expire_all()
    rejections = db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "framework.edit_rejected",
            AuditEvent.entity_id == procurement_id,
        )
    )
    assert rejections == 1
