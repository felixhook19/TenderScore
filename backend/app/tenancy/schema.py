"""Tenant-schema DDL helpers (see ADR-003).

Tenant tables are declared on `TenantBase` without a schema. A new tenant's
schema is created at the current head state with `create_tenant_tables`;
alembic migrations that change tenant tables loop over every existing
tenant schema. Invariant: all tenant schemas are at the global alembic
head.
"""

from sqlalchemy import Connection, text

# Import every module that declares TenantBase tables so the metadata is
# complete before create_all runs.
from app.anonymisation import models as _anonymisation_models  # noqa: F401
from app.core.db import TenantBase
from app.framework import models as _framework_models  # noqa: F401
from app.ingestion import models as _ingestion_models  # noqa: F401
from app.moderation import models as _moderation_models  # noqa: F401
from app.scoring import models as _scoring_models  # noqa: F401


def _with_schema(connection: Connection, schema_name: str, create: bool) -> None:
    # Connection.execution_options mutates the connection in place, so the
    # previous translate map must be restored afterwards — otherwise the
    # caller's subsequent unqualified statements (for example alembic's own
    # version table) are silently redirected into the tenant schema.
    previous = connection.get_execution_options().get("schema_translate_map")
    connection.execution_options(schema_translate_map={None: schema_name})
    try:
        if create:
            TenantBase.metadata.create_all(connection)
        else:
            TenantBase.metadata.drop_all(connection)
    finally:
        connection.execution_options(schema_translate_map=previous or {})


def create_tenant_tables(connection: Connection, schema_name: str) -> None:
    """Create all tenant tables in the given schema at head state."""
    _with_schema(connection, schema_name, create=True)


def drop_tenant_tables(connection: Connection, schema_name: str) -> None:
    """Drop all tenant tables in the given schema (migration downgrades)."""
    _with_schema(connection, schema_name, create=False)


def list_tenant_schemas(connection: Connection) -> list[str]:
    """All provisioned tenant schemas, from the platform tenants table."""
    rows = connection.execute(text("SELECT schema_name FROM platform.tenants ORDER BY 1"))
    return [row[0] for row in rows]
