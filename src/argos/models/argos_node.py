from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from argos.database.base import Base


class ArgosNodeFlowmeterMinute(Base):
    __tablename__ = "argos_node_flowmeter_minutes"
    __table_args__ = (
        UniqueConstraint("node_url", "window_start_utc", name="uq_argos_node_flowmeter_minutes_node_window"),
        Index("ix_argos_node_flowmeter_minutes_node_window", "node_url", "window_start_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    window_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pulse_count_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pulse_count_end: Mapped[int] = mapped_column(Integer, nullable=False)
    pulse_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    boot_total_l_start: Mapped[float | None] = mapped_column(Float)
    boot_total_l_end: Mapped[float | None] = mapped_column(Float)
    total_l_start: Mapped[float | None] = mapped_column(Float)
    total_l_end: Mapped[float | None] = mapped_column(Float)
    hydrological_year_l_start: Mapped[float | None] = mapped_column(Float)
    hydrological_year_l_end: Mapped[float | None] = mapped_column(Float)
    session_active_start: Mapped[bool | None] = mapped_column(Boolean)
    session_active_end: Mapped[bool | None] = mapped_column(Boolean)
    session_l_start: Mapped[float | None] = mapped_column(Float)
    session_l_end: Mapped[float | None] = mapped_column(Float)
    last_session_l_start: Mapped[float | None] = mapped_column(Float)
    last_session_l_end: Mapped[float | None] = mapped_column(Float)
    volume_l: Mapped[float] = mapped_column(Float, nullable=False)
    avg_flow_l_min: Mapped[float] = mapped_column(Float, nullable=False)
    max_flow_l_min: Mapped[float] = mapped_column(Float, nullable=False)
    samples_count: Mapped[int] = mapped_column(Integer, nullable=False)
    relay1_state_start: Mapped[bool | None] = mapped_column(Boolean)
    relay1_state_end: Mapped[bool | None] = mapped_column(Boolean)
    relay1_open_samples_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    relay1_open_fraction: Mapped[float | None] = mapped_column(Float)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ArgosNodeFlowmeterSession(Base):
    __tablename__ = "argos_node_flowmeter_sessions"
    __table_args__ = (
        UniqueConstraint("node_url", "closed_at_utc", name="uq_argos_node_flowmeter_sessions_node_closed_at"),
        Index("ix_argos_node_flowmeter_sessions_node_closed_at", "node_url", "closed_at_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    closed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_session_l: Mapped[float] = mapped_column(Float, nullable=False)
    pulse_count: Mapped[int | None] = mapped_column(Integer)
    total_l: Mapped[float | None] = mapped_column(Float)
    hydrological_year_l: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ArgosNodeFlowmeterResetEvent(Base):
    __tablename__ = "argos_node_flowmeter_reset_events"
    __table_args__ = (
        UniqueConstraint("node_url", "reset_type", "administrative_year", name="uq_argos_node_flowmeter_reset_year"),
        Index("ix_argos_node_flowmeter_reset_events_node_type", "node_url", "reset_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    reset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    administrative_year: Mapped[int] = mapped_column(Integer, nullable=False)
    reset_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
