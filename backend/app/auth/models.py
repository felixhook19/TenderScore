"""Identity, RBAC and session models (platform schema)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ROLE_VALUES = ("admin", "procurement_lead", "evaluator", "moderator", "observer_auditor")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_users_status"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("platform.tenants.id"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(128))
    totp_secret: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'procurement_lead', 'evaluator', 'moderator', "
            "'observer_auditor')",
            name="ck_user_roles_role",
        ),
        {"schema": "platform"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("platform.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("platform.tenants.id"))


class UserPrivilege(Base):
    """A distinct grant, never implied by any role (CLAUDE.md: the
    anonymisation-map privilege is separate from RBAC roles)."""

    __tablename__ = "user_privileges"
    __table_args__ = ({"schema": "platform"},)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("platform.users.id", ondelete="CASCADE"), primary_key=True
    )
    privilege: Mapped[str] = mapped_column(String(128), primary_key=True)


class SessionToken(Base):
    """Opaque, database-backed session: revocable and individually expirable.

    `status` lifecycle: pending_totp (password verified, second factor
    outstanding) -> active -> revoked.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_totp', 'active', 'revoked')", name="ck_sessions_status"
        ),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("platform.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
