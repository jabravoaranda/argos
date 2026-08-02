from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from argos.database.base import Base


class FieldEvent(Base):
    __tablename__ = "field_events"
    __table_args__ = (
        Index("ix_field_events_occurred_at", "occurred_at"),
        Index("ix_field_events_event_type", "event_type"),
        Index("ix_field_events_zone_slug", "zone_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    zone_slug: Mapped[str | None] = mapped_column(String(100))
    tree_reference: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
