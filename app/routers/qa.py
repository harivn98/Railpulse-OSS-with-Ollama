"""
Q&A router — natural-language question answering via the RAG pipeline.

POST  /qa/  — ask a question, optionally scoped to a track section.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas import QARequest, QAResponse
from app.services import rag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/", response_model=QAResponse)
async def ask_question(
    body: QARequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Ask a natural-language question about railway operations.

    The system:
      1. Embeds the question via Ollama.
      2. Retrieves semantically similar anomaly events and maintenance notes (pgvector).
      3. Sends the retrieved context + question to Ollama for a grounded answer.

    Optionally scope retrieval to a specific ``track_section``.
    """
    logger.info("Q&A request: %s (section=%s)", body.question[:80], body.track_section)
    response = await rag.answer(
        question=body.question,
        session=session,
        track_section=body.track_section,
    )
    return response
