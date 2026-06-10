"""Bootstrap CLI: tenant + first administrator, fully audited."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.verifier import verify_scope
from app.auth.models import User, UserRole
from app.tenancy.bootstrap import main
from app.tenancy.models import Tenant


def test_bootstrap_provisions_tenant_and_admin(
    db_session: Session, capsys: "object"
) -> None:
    suffix = uuid.uuid4().hex[:12]
    exit_code = main(
        [
            "--tenant-name",
            f"Bootstrap Council {suffix}",
            "--admin-email",
            f"bootstrap-{suffix}@example.org",
            "--admin-name",
            "Bootstrap Admin",
            "--admin-password",
            "a-bootstrap-password-123",
        ]
    )
    assert exit_code == 0

    tenant = db_session.scalar(
        select(Tenant).where(Tenant.name == f"Bootstrap Council {suffix}")
    )
    assert tenant is not None

    admin = db_session.scalar(
        select(User).where(User.email == f"bootstrap-{suffix}@example.org")
    )
    assert admin is not None
    role = db_session.get(UserRole, (admin.id, "admin"))
    assert role is not None

    events = db_session.scalars(
        select(AuditEvent.action).where(AuditEvent.tenant_id == tenant.id)
    ).all()
    assert "tenant.provisioned" in events
    assert "user.created" in events
    assert "rbac.role.granted" in events
    assert verify_scope(db_session, tenant.id).valid


def test_bootstrap_refuses_duplicate_tenants(db_session: Session) -> None:
    suffix = uuid.uuid4().hex[:12]
    args = [
        "--tenant-name",
        f"Duplicate Council {suffix}",
        "--admin-email",
        f"duplicate-{suffix}@example.org",
        "--admin-name",
        "Duplicate Admin",
        "--admin-password",
        "a-bootstrap-password-123",
    ]
    assert main(args) == 0
    assert main(args) == 1
