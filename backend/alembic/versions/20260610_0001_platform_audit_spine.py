"""Platform schema: tenancy, identity, RBAC and the append-only audit store.

Revision ID: 0001
Revises:
Create Date: 2026-06-10

The audit store's immutability is enforced at the database level, not by
convention: UPDATE/DELETE/TRUNCATE privileges are revoked from the
application role, and a trigger raises on any UPDATE/DELETE/TRUNCATE so
even the table owner cannot mutate history without first disabling the
trigger (which the chain verifier would then expose).

All migrations must be reversible (CLAUDE.md) — `downgrade` is never a no-op
for a migration that changes state.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA platform")

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schema_name", sa.String(63), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_tenants_name"),
        sa.UniqueConstraint("schema_name", name="uq_tenants_schema_name"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),
        schema="platform",
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("platform.tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("totp_secret", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_users_status"),
        schema="platform",
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("platform.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(32), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("platform.tenants.id"), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'procurement_lead', 'evaluator', 'moderator', "
            "'observer_auditor')",
            name="ck_user_roles_role",
        ),
        schema="platform",
    )

    op.create_table(
        "user_privileges",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("platform.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("privilege", sa.String(128), primary_key=True),
        schema="platform",
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("platform.users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        sa.CheckConstraint(
            "status IN ('pending_totp', 'active', 'revoked')", name="ck_sessions_status"
        ),
        schema="platform",
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("before_hash", sa.String(64), nullable=True),
        sa.Column("after_hash", sa.String(64), nullable=True),
        sa.Column("prompt_id", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("model_version", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_event_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.CheckConstraint("actor_type IN ('user', 'system')", name="ck_audit_actor_type"),
        schema="platform",
    )
    op.create_index(
        "ix_audit_events_tenant_id_id", "audit_events", ["tenant_id", "id"], schema="platform"
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id"],
        schema="platform",
    )

    # Append-only enforcement, layer 1: a trigger that raises on any attempt
    # to rewrite history. Applies to every role, including the table owner,
    # unless the trigger itself is disabled (which the verifier exposes).
    op.execute(
        """
        CREATE FUNCTION platform.audit_events_block_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON platform.audit_events
        FOR EACH ROW EXECUTE FUNCTION platform.audit_events_block_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON platform.audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION platform.audit_events_block_mutation()
        """
    )

    # Append-only enforcement, layer 2: revoke the privileges outright from
    # the application role (the migration runner) and from PUBLIC.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON platform.audit_events FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format(
                'REVOKE UPDATE, DELETE, TRUNCATE ON platform.audit_events FROM %I',
                current_user
            );
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_no_truncate ON platform.audit_events")
    op.execute("DROP TRIGGER audit_events_no_update_delete ON platform.audit_events")
    op.execute("DROP FUNCTION platform.audit_events_block_mutation()")
    op.drop_table("audit_events", schema="platform")
    op.drop_table("sessions", schema="platform")
    op.drop_table("user_privileges", schema="platform")
    op.drop_table("user_roles", schema="platform")
    op.drop_table("users", schema="platform")
    op.drop_table("tenants", schema="platform")
    op.execute("DROP SCHEMA platform")
