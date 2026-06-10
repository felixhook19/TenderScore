"""Framework models (tenant schema): procurements, lots, criteria tree,
band descriptors, spec requirements, lock events, calibration benchmarks."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantBase


class Procurement(TenantBase):
    __tablename__ = "procurements"
    __table_args__ = (
        CheckConstraint("regime IN ('PA23', 'PCR15')", name="ck_procurements_regime"),
        CheckConstraint(
            "status IN ('draft', 'locked', 'complete')", name="ck_procurements_status"
        ),
        UniqueConstraint("reference", name="uq_procurements_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(300))
    reference: Mapped[str] = mapped_column(String(100))
    regime: Mapped[str] = mapped_column(String(8), default="PA23")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    pinned_model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    framework_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    framework_lock_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Lot(TenantBase):
    __tablename__ = "lots"
    __table_args__ = (
        UniqueConstraint("procurement_id", "lot_number", name="uq_lots_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    lot_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))


class Criterion(TenantBase):
    """Criteria tree: a criterion with parent_id set is a sub-criterion."""

    __tablename__ = "criteria"
    __table_args__ = (
        UniqueConstraint("procurement_id", "ref", name="uq_criteria_ref"),
        CheckConstraint("weighting_pct >= 0 AND weighting_pct <= 100", name="ck_criteria_weight"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lots.id", ondelete="SET NULL"), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("criteria.id", ondelete="CASCADE"), nullable=True
    )
    ref: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    weighting_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    is_gate: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_rule: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    word_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_criterion: Mapped[bool] = mapped_column(Boolean, default=False)


class BandDescriptor(TenantBase):
    """Verbatim band descriptors; locked with the framework."""

    __tablename__ = "band_descriptors"
    __table_args__ = (
        UniqueConstraint("criterion_id", "band", name="uq_band_descriptors_band"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("criteria.id", ondelete="CASCADE"), index=True
    )
    band: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(100))
    descriptor_text: Mapped[str] = mapped_column(Text)


class SpecRequirement(TenantBase):
    __tablename__ = "spec_requirements"
    __table_args__ = (
        UniqueConstraint("criterion_id", "ref", name="uq_spec_requirements_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("criteria.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)


class FrameworkLockEvent(TenantBase):
    __tablename__ = "framework_lock_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    lock_hash: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(128))
    locked_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CalibrationBenchmark(TenantBase):
    """Buyer-scored benchmark answers; the calibration gate compares the
    engine's scores against these before live scoring may begin."""

    __tablename__ = "calibration_benchmarks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("criteria.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(300))
    answer_text: Mapped[str] = mapped_column(Text)
    buyer_score: Mapped[int] = mapped_column(Integer)
    engine_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    divergence_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    acceptance_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
