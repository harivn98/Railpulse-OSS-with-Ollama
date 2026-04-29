import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.database import Base


class TelemetryReading(Base):
    """Raw sensor reading ingested from a track section."""

    __tablename__ = "telemetry_readings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_section: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sensor_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnomalyEvent(Base):
    """An anomaly detected by dtaianomaly for a given sensor stream."""

    __tablename__ = "anomaly_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_section: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sensor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")  # low / medium / high / critical
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # pending → explained → acknowledged → resolved

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_context: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Fields populated by the Ollama explanation service
    llm_summary: Mapped[str | None] = mapped_column(Text)
    llm_probable_cause: Mapped[str | None] = mapped_column(Text)
    llm_recommendation: Mapped[str | None] = mapped_column(Text)

    # pgvector embedding of (track_section + sensor_type + llm_summary) for RAG retrieval
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embed_dim))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MaintenanceNote(Base):
    """Free-text maintenance note authored by an ops engineer."""

    __tablename__ = "maintenance_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_section: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)

    # pgvector embedding of the note text for RAG retrieval
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embed_dim))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
