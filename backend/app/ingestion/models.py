"""Ingestion models (tenant schema): bidders, submissions, question responses."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantBase


class Bidder(TenantBase):
    """Restricted table: legal identity. Evaluators see only the
    anonymisation token (M6); reads of the mapping require the distinct
    `anonymisation_map.read` privilege and are individually audited."""

    __tablename__ = "bidders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    legal_name: Mapped[str] = mapped_column(String(300))
    companies_house_no: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Submission(TenantBase):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bidders.id", ondelete="CASCADE"), index=True
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lots.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(300))
    original_object_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="received")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'ingesting', 'ingested', 'failed')",
            name="ck_submissions_status",
        ),
    )


class QuestionResponse(TenantBase):
    __tablename__ = "question_responses"
    __table_args__ = (
        CheckConstraint(
            "compliance_status IN ('pending', 'compliant', 'non_compliant', 'caveat_flagged')",
            name="ck_question_responses_compliance",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("criteria.id", ondelete="SET NULL"), nullable=True
    )
    criterion_ref: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    word_count: Mapped[int] = mapped_column(Integer)
    attachments: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    compliance_status: Mapped[str] = mapped_column(String(16), default="pending")
    compliance_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    injection_scan: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
