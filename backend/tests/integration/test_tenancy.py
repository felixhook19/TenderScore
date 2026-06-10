"""Schema-per-tenant provisioning."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.recorder import AuditRecorder
from app.tenancy.service import TenantProvisioningError, create_tenant
from tests.conftest import TenantFactory


def test_provisioning_creates_the_schema(
    make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    provisioned = make_tenant_with_admin()
    found = db_session.scalar(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = :name"),
        {"name": provisioned.tenant.schema_name},
    )
    assert found == provisioned.tenant.schema_name


def test_provisioning_is_audited_in_the_tenants_own_chain(
    make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    provisioned = make_tenant_with_admin()
    event = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "tenant.provisioned",
            AuditEvent.tenant_id == provisioned.tenant.id,
        )
    )
    assert event is not None
    assert event.actor_type == "system"
    assert event.entity_id == str(provisioned.tenant.id)
    assert event.after_hash is not None


def test_duplicate_tenant_names_are_rejected(
    make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    provisioned = make_tenant_with_admin()
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    with pytest.raises(TenantProvisioningError, match="already exists"):
        create_tenant(db_session, recorder, provisioned.tenant.name)
    db_session.rollback()
