from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from argos.database.base import Base


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("code", name="uq_data_sources_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    runs: Mapped[list["IngestionRun"]] = relationship(back_populates="source")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint("run_uuid", name="uq_ingestion_runs_run_uuid"),
        Index("ix_ingestion_runs_source_started", "source_id", "started_at_utc"),
        Index("ix_ingestion_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    run_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trigger: Mapped[str | None] = mapped_column(String(64))
    code_version: Mapped[str | None] = mapped_column(String(64))
    processing_version: Mapped[str | None] = mapped_column(String(64))
    parameters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    source: Mapped[DataSource] = relationship(back_populates="runs")
    items: Mapped[list["IngestionItem"]] = relationship(back_populates="run")


class IngestionItem(Base):
    __tablename__ = "ingestion_items"
    __table_args__ = (
        UniqueConstraint("run_id", "item_key", name="uq_ingestion_items_run_item_key"),
        Index("ix_ingestion_items_run_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(512), nullable=False)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    source_external_id: Mapped[str | None] = mapped_column(String(512), index=True)
    requested_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    run: Mapped[IngestionRun] = relationship(back_populates="items")


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    __table_args__ = (
        UniqueConstraint("source_id", "scope", "scope_key", name="uq_sync_cursors_source_scope_key"),
        Index("ix_sync_cursors_source_scope", "source_id", "scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    cursor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cursor_value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    last_successful_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceArtifact(Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (
        Index("ix_source_artifacts_source_role", "source_id", "role"),
        Index("ix_source_artifacts_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    ingestion_item_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_items.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="local_filesystem",
        server_default="local_filesystem",
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    regenerable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    original_filename: Mapped[str | None] = mapped_column(String(512))
    provider_external_id: Mapped[str | None] = mapped_column(String(512), index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    verified_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
