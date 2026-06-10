"""Moderation models (tenant schema): decisions and generated packs."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantBase


class ModerationDecision(TenantBase):
    __tablename__ = "moderation_decisions"
    __table_args__ = (
        CheckConstraint("action IN ('confirm', 'amend')", name="ck_moderation_action"),
        # Mandatory rationale on amend, enforced in the database as well as
        # the service layer.
        CheckConstraint(
            "action != 'amend' OR (rationale IS NOT NULL AND length(rationale) > 0)",
            name="ck_moderation_amend_rationale",
        ),
        UniqueConstraint("recommendation_id", name="uq_moderation_recommendation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recommendations.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(16))
    final_score: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModerationPack(TenantBase):
    __tablename__ = "moderation_packs"
    __table_args__ = (
        UniqueConstraint("procurement_id", "version", name="uq_moderation_packs_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    file_format: Mapped[str] = mapped_column(String(8), default="docx")
    generated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
