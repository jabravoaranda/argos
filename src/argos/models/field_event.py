from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from argos.database.base import Base

if TYPE_CHECKING:
    from argos.models.plants import FieldEventPlantUnit


class FieldEventPhoto(Base):
    __tablename__ = "field_event_photos"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_field_event_photos_sha256"),
        Index("ix_field_event_photos_field_event_id", "field_event_id"),
        Index("ix_field_event_photos_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_event_id: Mapped[int] = mapped_column(ForeignKey("field_events.id"), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_source: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_code: Mapped[str | None] = mapped_column(String(100))
    resolver_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FieldEvent(Base):
    __tablename__ = "field_events"
    __table_args__ = (
        Index("ix_field_events_occurred_at", "occurred_at"),
        Index("ix_field_events_event_type", "event_type"),
        Index("ix_field_events_zone_slug", "zone_slug"),
        Index("ix_field_events_target_type", "target_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    zone_slug: Mapped[str | None] = mapped_column(String(100))
    tree_reference: Mapped[str | None] = mapped_column(String(255))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_value: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(64))
    photo_storage_path: Mapped[str | None] = mapped_column(String(500))
    photo_mime_type: Mapped[str | None] = mapped_column(String(100))
    photo_original_filename: Mapped[str | None] = mapped_column(String(255))
    photo_size_bytes: Mapped[int | None] = mapped_column(Integer)
    photo_sha256: Mapped[str | None] = mapped_column(String(64))
    photo_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    plant_links: Mapped[list["FieldEventPlantUnit"]] = relationship(cascade="all, delete-orphan")
    photos: Mapped[list[FieldEventPhoto]] = relationship(cascade="all, delete-orphan")
