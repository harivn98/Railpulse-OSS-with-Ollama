"""
Telemetry router — ingest, query, and list track sections.

POST  /telemetry/ingest    — bulk-ingest sensor readings (≤ 500 per call).
GET   /telemetry/           — query readings with filters.
GET   /telemetry/sections   — list distinct track sections.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import TelemetryReading
from app.schemas import (
    IngestResponse,
    TelemetryBatchIn,
    TelemetryReadingOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telemetry", tags=["telemetry"])


# ── POST /telemetry/ingest ────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest_readings(
    batch: TelemetryBatchIn,
    session: AsyncSession = Depends(get_session),
):
    """Ingest a batch of sensor readings into PostgreSQL."""
    rows = [
        TelemetryReading(
            track_section=r.track_section,
            sensor_type=r.sensor_type,
            value=r.value,
            unit=r.unit,
            recorded_at=r.recorded_at,
        )
        for r in batch.readings
    ]
    session.add_all(rows)
    await session.commit()
    return IngestResponse(ingested=len(rows))


# ── GET /telemetry/ ───────────────────────────────────────────────────────

@router.get("/", response_model=list[TelemetryReadingOut])
async def query_readings(
    section: str | None = Query(None, description="Filter by track section"),
    sensor_type: str | None = Query(None, description="Filter by sensor type"),
    start: datetime | None = Query(None, description="Start of time range (ISO 8601)"),
    end: datetime | None = Query(None, description="End of time range (ISO 8601)"),
    limit: int = Query(200, ge=1, le=2000, description="Max rows returned"),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Query telemetry readings with optional filters."""
    stmt = select(TelemetryReading).order_by(TelemetryReading.recorded_at.desc())

    if section:
        stmt = stmt.where(TelemetryReading.track_section == section)
    if sensor_type:
        stmt = stmt.where(TelemetryReading.sensor_type == sensor_type)
    if start:
        stmt = stmt.where(TelemetryReading.recorded_at >= start)
    if end:
        stmt = stmt.where(TelemetryReading.recorded_at <= end)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


# ── GET /telemetry/sections ───────────────────────────────────────────────

@router.get("/sections", response_model=list[str])
async def list_sections(
    session: AsyncSession = Depends(get_session),
):
    """Return all distinct track sections present in the database."""
    result = await session.execute(
        select(distinct(TelemetryReading.track_section)).order_by(TelemetryReading.track_section)
    )
    return result.scalars().all()
