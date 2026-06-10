"""Job queue, prompt registry, and the tenant-schema evaluation tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-10

Tenant tables are created in every existing tenant schema (ADR-003); newly
provisioned tenants get them at head state from the provisioning service.

All migrations must be reversible (CLAUDE.md).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.tenancy.schema import create_tenant_tables, drop_tenant_tables, list_tenant_schemas

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"
        ),
        schema="platform",
    )

    op.create_table(
        "prompt_registry",
        sa.Column("prompt_id", sa.String(128), primary_key=True),
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column(
            "released_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("released_by", sa.String(200), nullable=True),
        schema="platform",
    )

    connection = op.get_bind()
    for schema_name in list_tenant_schemas(connection):
        create_tenant_tables(connection, schema_name)


def downgrade() -> None:
    connection = op.get_bind()
    for schema_name in list_tenant_schemas(connection):
        drop_tenant_tables(connection, schema_name)
    op.drop_table("prompt_registry", schema="platform")
    op.drop_table("jobs", schema="platform")
