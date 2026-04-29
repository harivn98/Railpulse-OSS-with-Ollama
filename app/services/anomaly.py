"""
Anomaly detection service.

Runs a background asyncio task that periodically:
  1. Pulls recent telemetry from PostgreSQL, grouped by (track_section, sensor_type).
  2. Runs dtaianomaly's IsolationForest on each sensor stream.
  3. If the normalised anomaly score exceeds the configured threshold, creates an
     AnomalyEvent row and dispatches it for LLM explanation.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AnomalyEvent, TelemetryReading
from app.services import ollama_client

# dtaianomaly wraps sklearn anomaly detectors behind a unified interface.
# IsolationForest is a good default — no labelled data required.
try:
    from dtaianomaly.anomaly_detection import IsolationForest as DTAIForest
    _USE_DTAI = True
except ImportError:
    from sklearn.ensemble import IsolationForest as SKForest  # type: ignore[assignment]
    _USE_DTAI = False

from sqlalchemy import select

logger = logging.getLogger(__name__)

_SENSOR_TYPES = ["vibration", "temperature", "speed", "axle_load"]


# ---------------------------------------------------------------------------
# Detector factory
# ---------------------------------------------------------------------------

def _make_detector():
    if _USE_DTAI:
        return DTAIForest(window_size=10, n_estimators=100, random_state=42)
    return SKForest(n_estimators=100, contamination=0.05, random_state=42)


def _score_series(values: np.ndarray) -> np.ndarray:
    """
    Fit and score a 1-D time series. Returns a normalised score in [0, 1]
    where 1 is most anomalous.
    """
    X = values.reshape(-1, 1)
    detector = _make_detector()

    if _USE_DTAI:
        detector.fit(X)
        scores = detector.decision_function(X)
    else:
        detector.fit(X)
        # sklearn returns negative scores — flip and normalise
        raw = -detector.decision_function(X)
        scores = raw

    # Normalise to [0, 1]
    mn, mx = scores.min(), scores.max()
    if mx == mn:
        return np.zeros_like(scores)
    return (scores - mn) / (mx - mn)


def _severity_from_score(score: float) -> str:
    if score >= 0.9:
        return "critical"
    if score >= 0.75:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Core detection sweep
# ---------------------------------------------------------------------------

async def _run_detection_sweep() -> None:
    """Pull recent readings and raise anomaly events for any outlier streams."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.anomaly_window_size * 5)

    async with AsyncSessionLocal() as session:
        # Fetch all recent readings
        result = await session.execute(
            select(TelemetryReading)
            .where(TelemetryReading.recorded_at >= cutoff)
            .order_by(TelemetryReading.recorded_at)
        )
        readings = result.scalars().all()

    if not readings:
        return

    # Group by (track_section, sensor_type)
    groups: dict[tuple[str, str], list[TelemetryReading]] = {}
    for r in readings:
        key = (r.track_section, r.sensor_type)
        groups.setdefault(key, []).append(r)

    for (track_section, sensor_type), group_readings in groups.items():
        if len(group_readings) < 10:
            # Not enough data to run the detector yet
            continue

        values = np.array([r.value for r in group_readings])
        scores = _score_series(values)

        # Check the most recent reading's score
        latest_score = float(scores[-1])
        if latest_score < settings.anomaly_threshold:
            continue

        logger.info(
            "Anomaly detected: section=%s sensor=%s score=%.3f",
            track_section, sensor_type, latest_score,
        )

        await _create_and_explain_event(
            track_section=track_section,
            sensor_type=sensor_type,
            anomaly_score=latest_score,
            window_readings=group_readings,
        )


async def _create_and_explain_event(
    track_section: str,
    sensor_type: str,
    anomaly_score: float,
    window_readings: list[TelemetryReading],
) -> None:
    """Persist an AnomalyEvent and enrich it with an LLM explanation."""
    raw_context = {
        "readings": [
            {
                "recorded_at": r.recorded_at.isoformat(),
                "value": r.value,
                "unit": r.unit,
            }
            for r in window_readings
        ]
    }
    window_start = window_readings[0].recorded_at
    window_end = window_readings[-1].recorded_at

    # Get LLM explanation (runs concurrently with DB write below)
    explanation = await ollama_client.explain_alert(
        track_section=track_section,
        sensor_type=sensor_type,
        anomaly_score=anomaly_score,
        window_readings=raw_context["readings"],
    )

    # Generate embedding for RAG retrieval
    embed_text = (
        f"Track section {track_section} | Sensor {sensor_type} | "
        f"{explanation['summary']} | Cause: {explanation['probable_cause']}"
    )
    try:
        embedding = await ollama_client.embed(embed_text)
    except Exception as exc:
        logger.warning("Embedding failed for anomaly event: %s", exc)
        embedding = None

    async with AsyncSessionLocal() as session:
        event = AnomalyEvent(
            track_section=track_section,
            sensor_type=sensor_type,
            anomaly_score=anomaly_score,
            severity=explanation["severity"],
            status="explained",
            window_start=window_start,
            window_end=window_end,
            raw_context=raw_context,
            llm_summary=explanation["summary"],
            llm_probable_cause=explanation["probable_cause"],
            llm_recommendation=explanation["recommendation"],
            embedding=embedding,
        )
        session.add(event)
        await session.commit()
        logger.info("AnomalyEvent created: id=%s severity=%s", event.id, event.severity)


# ---------------------------------------------------------------------------
# Background task lifecycle
# ---------------------------------------------------------------------------

_task: asyncio.Task | None = None


async def start_background_detector() -> None:
    global _task
    _task = asyncio.create_task(_detection_loop())
    logger.info("Anomaly detection background task started (interval=%ds)", settings.anomaly_poll_interval)


async def _detection_loop() -> None:
    while True:
        try:
            await _run_detection_sweep()
        except Exception as exc:
            logger.error("Detection sweep error: %s", exc, exc_info=True)
        await asyncio.sleep(settings.anomaly_poll_interval)


async def stop_background_detector() -> None:
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
