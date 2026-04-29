"""
RAG (Retrieval-Augmented Generation) pipeline.

embed_document()  — generate an Ollama embedding and persist it on the row.
retrieve()        — cosine similarity search over AnomalyEvent and MaintenanceNote.
answer()          — full RAG Q&A: embed question → retrieve → generate with Ollama.
"""

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AnomalyEvent, MaintenanceNote
from app.schemas import QAResponse, QASource
from app.services import ollama_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are RailPulse, an expert railway operations assistant. "
    "Answer the engineer's question using ONLY the provided context. "
    "If the context does not contain enough information, say so clearly. "
    "Be concise and technical."
)


# ---------------------------------------------------------------------------
# Embed and store
# ---------------------------------------------------------------------------

async def embed_anomaly_event(event_id: uuid.UUID, session: AsyncSession) -> None:
    """Generate and persist an embedding for an AnomalyEvent."""
    event = await session.get(AnomalyEvent, event_id)
    if not event or event.llm_summary is None:
        return
    text_to_embed = (
        f"Track section {event.track_section} sensor {event.sensor_type}. "
        f"{event.llm_summary} Probable cause: {event.llm_probable_cause}. "
        f"Recommendation: {event.llm_recommendation}."
    )
    try:
        event.embedding = await ollama_client.embed(text_to_embed)
        await session.commit()
    except Exception as exc:
        logger.warning("embed_anomaly_event failed for %s: %s", event_id, exc)


async def embed_maintenance_note(note_id: uuid.UUID, session: AsyncSession) -> None:
    """Generate and persist an embedding for a MaintenanceNote."""
    note = await session.get(MaintenanceNote, note_id)
    if not note:
        return
    text_to_embed = f"Track section {note.track_section}: {note.note}"
    try:
        note.embedding = await ollama_client.embed(text_to_embed)
        await session.commit()
    except Exception as exc:
        logger.warning("embed_maintenance_note failed for %s: %s", note_id, exc)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

async def retrieve(
    query_embedding: list[float],
    session: AsyncSession,
    track_section: str | None = None,
    k: int | None = None,
) -> list[dict]:
    """
    Cosine similarity search over both AnomalyEvent and MaintenanceNote tables.

    Returns a merged, de-duplicated list of the top-k most relevant chunks,
    each as a dict with keys: source_type, source_id, track_section, snippet, distance.
    """
    k = k or settings.rag_top_k
    vec_literal = f"[{','.join(str(v) for v in query_embedding)}]"

    results = []

    # --- AnomalyEvent retrieval ---
    ae_query = (
        select(
            AnomalyEvent.id,
            AnomalyEvent.track_section,
            AnomalyEvent.sensor_type,
            AnomalyEvent.llm_summary,
            AnomalyEvent.llm_probable_cause,
            AnomalyEvent.severity,
            AnomalyEvent.created_at,
            AnomalyEvent.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .where(AnomalyEvent.embedding.isnot(None))
        .order_by(text("distance"))
        .limit(k)
    )
    if track_section:
        ae_query = ae_query.where(AnomalyEvent.track_section == track_section)

    ae_rows = (await session.execute(ae_query)).all()
    for row in ae_rows:
        snippet = (
            f"[Anomaly — {row.sensor_type} on {row.track_section}, "
            f"severity={row.severity}, {row.created_at.date()}] "
            f"{row.llm_summary or ''} {row.llm_probable_cause or ''}"
        )
        results.append({
            "source_type": "anomaly_event",
            "source_id": row.id,
            "track_section": row.track_section,
            "snippet": snippet.strip(),
            "distance": row.distance,
        })

    # --- MaintenanceNote retrieval ---
    mn_query = (
        select(
            MaintenanceNote.id,
            MaintenanceNote.track_section,
            MaintenanceNote.author,
            MaintenanceNote.note,
            MaintenanceNote.created_at,
            MaintenanceNote.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .where(MaintenanceNote.embedding.isnot(None))
        .order_by(text("distance"))
        .limit(k)
    )
    if track_section:
        mn_query = mn_query.where(MaintenanceNote.track_section == track_section)

    mn_rows = (await session.execute(mn_query)).all()
    for row in mn_rows:
        snippet = (
            f"[Maintenance note — {row.track_section}, {row.created_at.date()}, by {row.author}] "
            f"{row.note}"
        )
        results.append({
            "source_type": "maintenance_note",
            "source_id": row.id,
            "track_section": row.track_section,
            "snippet": snippet.strip(),
            "distance": row.distance,
        })

    # Sort merged results by distance and keep top-k
    results.sort(key=lambda x: x["distance"])
    return results[:k]


# ---------------------------------------------------------------------------
# Full RAG pipeline
# ---------------------------------------------------------------------------

async def answer(question: str, session: AsyncSession, track_section: str | None = None) -> QAResponse:
    """
    End-to-end RAG:
      1. Embed the question.
      2. Retrieve semantically similar context chunks.
      3. Pass context + question to Ollama for a grounded answer.
    """
    # 1. Embed question
    try:
        q_embedding = await ollama_client.embed(question)
    except Exception as exc:
        logger.error("Failed to embed question: %s", exc)
        return QAResponse(
            answer="Embedding service unavailable. Please ensure Ollama is running.",
            sources=[],
        )

    # 2. Retrieve context
    chunks = await retrieve(q_embedding, session, track_section=track_section)

    if not chunks:
        return QAResponse(
            answer="No relevant context found in the database for that question.",
            sources=[],
        )

    # 3. Build context block
    context_block = "\n\n".join(
        f"[{i + 1}] {c['snippet']}" for i, c in enumerate(chunks)
    )

    user_message = (
        f"Context:\n{context_block}\n\n"
        f"Engineer's question: {question}"
    )

    # 4. Generate
    try:
        answer_text = await ollama_client.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )
    except Exception as exc:
        logger.error("Ollama chat failed during RAG: %s", exc)
        answer_text = "LLM generation failed. Check Ollama service."

    sources = [
        QASource(
            source_type=c["source_type"],
            source_id=c["source_id"],
            track_section=c["track_section"],
            snippet=c["snippet"][:300],
        )
        for c in chunks
    ]

    return QAResponse(answer=answer_text, sources=sources)
