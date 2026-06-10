"""Tenant lifecycle: schema-per-tenant provisioning.

Provisioning is a platform operation performed via the bootstrap CLI (there
is deliberately no public endpoint for it in v1). Every provisioning step is
audited; the new tenant's audit chain begins with its provisioning event.
"""

import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.hashing import state_hash
from app.audit.recorder import AuditRecorder
from app.tenancy.models import Tenant
from app.tenancy.schema import create_tenant_tables

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_SCHEMA_PREFIX = "tenant_"
# PostgreSQL identifier limit is 63 bytes.
_MAX_SLUG_LENGTH = 63 - len(_SCHEMA_PREFIX)


class TenantProvisioningError(Exception):
    """Raised when a tenant cannot be provisioned; message is safe to show."""


def schema_name_for(tenant_name: str) -> str:
    """Derive a valid, deterministic schema name from a tenant name."""
    slug = _SLUG_PATTERN.sub("_", tenant_name.strip().lower()).strip("_")
    slug = slug[:_MAX_SLUG_LENGTH].rstrip("_")
    if not slug or not slug[0].isalpha():
        raise TenantProvisioningError(
            "The tenant name must contain at least one letter and produce a usable "
            "schema name."
        )
    return f"{_SCHEMA_PREFIX}{slug}"


def create_tenant(session: Session, recorder: AuditRecorder, name: str) -> Tenant:
    """Create the tenant record and its dedicated schema, audited."""
    cleaned = name.strip()
    if not cleaned:
        raise TenantProvisioningError("The tenant name must not be empty.")

    schema_name = schema_name_for(cleaned)
    existing = session.scalar(
        select(Tenant).where((Tenant.name == cleaned) | (Tenant.schema_name == schema_name))
    )
    if existing is not None:
        raise TenantProvisioningError("A tenant with this name already exists.")

    tenant = Tenant(name=cleaned, schema_name=schema_name)
    session.add(tenant)
    session.flush()

    # schema_name is derived above from a strict [a-z0-9_] slug; quote anyway.
    session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    create_tenant_tables(session.connection(), schema_name)

    recorder.record(
        "tenant.provisioned",
        entity_type="tenant",
        entity_id=str(tenant.id),
        after_hash=state_hash(
            {"id": tenant.id, "name": tenant.name, "schema_name": tenant.schema_name}
        ),
        tenant_id=tenant.id,
    )
    return tenant
