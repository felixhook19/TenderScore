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


def create_tenant_tables(connection: Connection, schema_name: str) -> None:
    """Create all tenant tables in the given schema at head state."""
    translated = connection.execution_options(schema_translate_map={None: schema_name})
    TenantBase.metadata.create_all(translated)


def drop_tenant_tables(connection: Connection, schema_name: str) -> None:
    """Drop all tenant tables in the given schema (migration downgrades)."""
    translated = connection.execution_options(schema_translate_map={None: schema_name})
    TenantBase.metadata.drop_all(translated)


def list_tenant_schemas(connection: Connection) -> list[str]:
    """All provisioned tenant schemas, from the platform tenants table."""
    rows = connection.execute(text("SELECT schema_name FROM platform.tenants ORDER BY 1"))
    return [row[0] for row in rows]
