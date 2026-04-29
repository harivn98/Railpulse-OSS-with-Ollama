"""
Maintenance notes router — create and list maintenance notes.

POST  /maintenance/   — create a new maintenance note (auto-embedded for RAG).
GET   /maintenance/   — list notes, optionally filtered by track section.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import MaintenanceNote
from app.schemas import MaintenanceNoteIn, MaintenanceNoteOut
from app.services import rag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/maintenance", tags=["maintenance"])


# ── POST /maintenance/ ────────────────────────────────────────────────────

@router.post("/", response_model=MaintenanceNoteOut, status_code=201)
async def create_note(
    body: MaintenanceNoteIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Create a maintenance note.

    An embedding is generated asynchronously so the note becomes searchable
    via the RAG Q&A endpoint.
    """
    note = MaintenanceNote(
        track_section=body.track_section,
        author=body.author,
        note=body.note,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)

    # Fire-and-forget embedding generation
    background_tasks.add_task(_embed_note_background, note.id)

    logger.info("Maintenance note created: id=%s section=%s", note.id, note.track_section)
    return note


async def _embed_note_background(note_id):
    """Background task: open a fresh session and embed the note."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await rag.embed_maintenance_note(note_id, session)


# ── GET /maintenance/ ─────────────────────────────────────────────────────

@router.get("/", response_model=list[MaintenanceNoteOut])
async def list_notes(
    section: str | None = Query(None, description="Filter by track section"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List maintenance notes, newest first."""
    stmt = select(MaintenanceNote).order_by(MaintenanceNote.created_at.desc())

    if section:
        stmt = stmt.where(MaintenanceNote.track_section == section)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()
