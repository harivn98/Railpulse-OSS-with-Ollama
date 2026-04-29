"""
Alerts router — list, detail, status transitions, and summary stats for anomaly events.

GET    /alerts/               — paginated list with filters.
GET    /alerts/summary/stats  — aggregate counts by severity and status.
GET    /alerts/{id}           — full detail including raw_context.
PATCH  /alerts/{id}/status    — transition to acknowledged / resolved.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AnomalyEvent
from app.schemas import (
    AlertStatsOut,
    AnomalyEventDetail,
    AnomalyEventOut,
    StatusUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])

# Allowed status transitions — only forward movement
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":      {"acknowledged", "resolved"},
    "explained":    {"acknowledged", "resolved"},
    "acknowledged": {"resolved"},
    "resolved":     set(),          # terminal state
}


# ── GET /alerts/ ──────────────────────────────────────────────────────────

@router.get("/", response_model=list[AnomalyEventOut])
async def list_alerts(
    section: str | None = Query(None, description="Filter by track section"),
    severity: str | None = Query(None, description="Filter by severity level"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List anomaly events, newest first, with optional filters."""
    stmt = select(AnomalyEvent).order_by(AnomalyEvent.created_at.desc())

    if section:
        stmt = stmt.where(AnomalyEvent.track_section == section)
    if severity:
        stmt = stmt.where(AnomalyEvent.severity == severity)
    if status:
        stmt = stmt.where(AnomalyEvent.status == status)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


# ── GET /alerts/summary/stats ─────────────────────────────────────────────

@router.get("/summary/stats", response_model=AlertStatsOut)
async def alert_stats(
    session: AsyncSession = Depends(get_session),
):
    """Return aggregate alert counts grouped by severity and status."""
    # Total count
    total_result = await session.execute(select(func.count(AnomalyEvent.id)))
    total = total_result.scalar() or 0

    # By severity
    sev_result = await session.execute(
        select(AnomalyEvent.severity, func.count(AnomalyEvent.id))
        .group_by(AnomalyEvent.severity)
    )
    by_severity = {row[0]: row[1] for row in sev_result.all()}

    # By status
    stat_result = await session.execute(
        select(AnomalyEvent.status, func.count(AnomalyEvent.id))
        .group_by(AnomalyEvent.status)
    )
    by_status = {row[0]: row[1] for row in stat_result.all()}

    return AlertStatsOut(total=total, by_severity=by_severity, by_status=by_status)


# ── GET /alerts/{id} ──────────────────────────────────────────────────────

@router.get("/{alert_id}", response_model=AnomalyEventDetail)
async def get_alert(
    alert_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Fetch a single anomaly event with full LLM explanation and raw context."""
    event = await session.get(AnomalyEvent, alert_id)
    if not event:
        raise HTTPException(status_code=404, detail="Anomaly event not found")
    return event


# ── PATCH /alerts/{id}/status ─────────────────────────────────────────────

@router.patch("/{alert_id}/status", response_model=AnomalyEventOut)
async def update_alert_status(
    alert_id: uuid.UUID,
    body: StatusUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Transition an alert's status (acknowledged → resolved, etc.)."""
    event = await session.get(AnomalyEvent, alert_id)
    if not event:
        raise HTTPException(status_code=404, detail="Anomaly event not found")

    allowed = _VALID_TRANSITIONS.get(event.status, set())
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from '{event.status}' to '{body.status}'. "
                   f"Allowed: {sorted(allowed) if allowed else 'none (terminal state)'}.",
        )

    event.status = body.status
    await session.commit()
    await session.refresh(event)
    logger.info("Alert %s status → %s", alert_id, body.status)
    return event
