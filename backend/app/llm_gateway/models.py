"""Prompt registry model (platform schema). Prompts are versioned, hashed
artefacts — never inline strings (CLAUDE.md rule 2)."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PromptRegistryEntry(Base):
    __tablename__ = "prompt_registry"
    __table_args__ = ({"schema": "platform"},)

    prompt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sha256_hash: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(String(500))
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    released_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
