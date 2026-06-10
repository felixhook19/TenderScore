"""Scoring models (tenant schema): runs, passes, recommendations."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class ScoringRun(TenantBase):
    """One run = one criterion x one bidder, in strict isolation."""

    __tablename__ = "scoring_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'recommended', 'escalated', "
            "'failed', 'blocked')",
            name="ck_scoring_runs_status",
        ),
        UniqueConstraint(
            "procurement_id", "criterion_id", "bidder_id", name="uq_scoring_runs_context"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("criteria.id", ondelete="CASCADE")
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bidders.id", ondelete="CASCADE")
    )
    question_response_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("question_responses.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")
    pass_count_target: Mapped[int] = mapped_column(Integer, default=3)
    model_version: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScoringPass(TenantBase):
    __tablename__ = "scoring_passes"
    __table_args__ = (
        UniqueConstraint("run_id", "pass_number", "attempt", name="uq_scoring_passes_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scoring_runs.id", ondelete="CASCADE"), index=True
    )
    pass_number: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    raw_output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_failures: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injection_suspicion: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Recommendation(TenantBase):
    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint(
            "confidence_tier IN ('converged', 'moderate', 'escalate')",
            name="ck_recommendations_tier",
        ),
        UniqueConstraint("run_id", name="uq_recommendations_run"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scoring_runs.id", ondelete="CASCADE")
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    justification: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    requirements: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    weaknesses: Mapped[list[str]] = mapped_column(JSON, default=list)
    variance: Mapped[int] = mapped_column(Integer, default=0)
    confidence_tier: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
