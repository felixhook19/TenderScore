"""Anonymisation models (tenant schema)."""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantBase


class AnonymisationMapEntry(TenantBase):
    """bidder -> token ('Bidder A', ...). Every read is audited; reading
    requires the distinct `anonymisation_map.read` privilege."""

    __tablename__ = "anonymisation_map"
    __table_args__ = (
        UniqueConstraint("procurement_id", "token", name="uq_anonymisation_token"),
    )

    bidder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bidders.id", ondelete="CASCADE"), primary_key=True
    )
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(32))
