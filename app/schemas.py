"""
RailPulse OSS — Pydantic v2 request / response schemas.

Covers telemetry ingestion, alert CRUD, maintenance notes, and RAG Q&A.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# Telemetry
# ═══════════════════════════════════════════════════════════════════════════

class TelemetryReadingIn(BaseModel):
    """Single sensor reading sent by the simulator."""
    track_section: str = Field(..., max_length=32, examples=["A1"])
    sensor_type: str = Field(..., max_length=64, examples=["vibration"])
    value: float = Field(..., examples=[12.34])
    unit: str = Field(..., max_length=32, examples=["Hz"])
    recorded_at: datetime


class TelemetryBatchIn(BaseModel):
    """Batch wrapper for ingestion — up to 500 readings per call."""
    readings: list[TelemetryReadingIn] = Field(..., max_length=500)


class TelemetryReadingOut(BaseModel):
    id: uuid.UUID
    track_section: str
    sensor_type: str
    value: float
    unit: str
    recorded_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class IngestResponse(BaseModel):
    ingested: int


# ═══════════════════════════════════════════════════════════════════════════
# Alerts (Anomaly Events)
# ═══════════════════════════════════════════════════════════════════════════

SeverityLevel = Literal["low", "medium", "high", "critical"]
AlertStatus = Literal["pending", "explained", "acknowledged", "resolved"]


class AnomalyEventOut(BaseModel):
    id: uuid.UUID
    track_section: str
    sensor_type: str
    anomaly_score: float
    severity: SeverityLevel
    status: AlertStatus
    window_start: datetime
    window_end: datetime
    llm_summary: str | None = None
    llm_probable_cause: str | None = None
    llm_recommendation: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnomalyEventDetail(AnomalyEventOut):
    """Full event detail — includes the raw sensor context JSON."""
    raw_context: dict


class StatusUpdate(BaseModel):
    """PATCH body to transition alert status."""
    status: Literal["acknowledged", "resolved"]


class AlertStatsOut(BaseModel):
    """Aggregate counts by severity and status."""
    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Maintenance Notes
# ═══════════════════════════════════════════════════════════════════════════

class MaintenanceNoteIn(BaseModel):
    track_section: str = Field(..., max_length=32)
    author: str = Field(..., max_length=128)
    note: str = Field(..., min_length=1)


class MaintenanceNoteOut(BaseModel):
    id: uuid.UUID
    track_section: str
    author: str
    note: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Q&A (RAG)
# ═══════════════════════════════════════════════════════════════════════════

class QARequest(BaseModel):
    question: str = Field(..., min_length=3, examples=["Why was Track Section A1 flagged yesterday?"])
    track_section: str | None = Field(None, max_length=32, examples=["A1"])


class QASource(BaseModel):
    source_type: str          # "anomaly_event" | "maintenance_note"
    source_id: uuid.UUID
    track_section: str
    snippet: str


class QAResponse(BaseModel):
    answer: str
    sources: list[QASource]
