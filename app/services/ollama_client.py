"""
Thin async wrapper around the Ollama local API.

Exposes:
  - chat()          — general generation
  - explain_alert() — structured JSON alert explanation
  - embed()         — vector embedding for a piece of text
"""

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120.0)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

async def chat(messages: list[dict], model: str | None = None, json_schema: dict | None = None) -> str:
    """Call /api/chat and return the assistant text content."""
    payload: dict[str, Any] = {
        "model": model or settings.ollama_chat_model,
        "messages": messages,
        "stream": False,
    }
    if json_schema:
        payload["format"] = json_schema

    response = await _client.post("/api/chat", json=payload)
    response.raise_for_status()
    data = response.json()
    return data["message"]["content"]


async def embed(text: str, model: str | None = None) -> list[float]:
    """Call /api/embed and return a flat float vector."""
    payload = {
        "model": model or settings.ollama_embed_model,
        "input": text,
    }
    response = await _client.post("/api/embed", json=payload)
    response.raise_for_status()
    data = response.json()
    # Ollama returns {"embeddings": [[...], ...]} — we embed one string so take [0]
    return data["embeddings"][0]


# ---------------------------------------------------------------------------
# Domain-level helper: anomaly alert explanation
# ---------------------------------------------------------------------------

_ALERT_SCHEMA = {
    "type": "object",
    "properties": {
        "severity":        {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "summary":         {"type": "string"},
        "probable_cause":  {"type": "string"},
        "recommendation":  {"type": "string"},
    },
    "required": ["severity", "summary", "probable_cause", "recommendation"],
}

_SYSTEM_PROMPT = (
    "You are a railway maintenance AI assistant. "
    "Analyse the provided sensor anomaly and return a JSON object with exactly these fields: "
    "severity (low/medium/high/critical), summary (one sentence), "
    "probable_cause (one or two sentences), recommendation (concrete next steps). "
    "Be concise and technically precise."
)


async def explain_alert(
    track_section: str,
    sensor_type: str,
    anomaly_score: float,
    window_readings: list[dict],
) -> dict[str, str]:
    """
    Ask Ollama to explain a detected anomaly.

    Returns a dict with keys: severity, summary, probable_cause, recommendation.
    Falls back to a default dict on any error so the pipeline never blocks.
    """
    context_lines = [
        f"  t={r['recorded_at']}  value={r['value']} {r['unit']}"
        for r in window_readings[-20:]   # send the 20 most recent readings
    ]
    user_message = (
        f"Track section: {track_section}\n"
        f"Sensor type: {sensor_type}\n"
        f"Anomaly score: {anomaly_score:.3f} (0=normal, 1=highly anomalous)\n\n"
        f"Recent readings in the anomaly window:\n" + "\n".join(context_lines)
    )

    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            json_schema=_ALERT_SCHEMA,
        )
        # Ollama may wrap the JSON in markdown fences — strip them
        raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as exc:
        logger.error("Ollama explain_alert failed: %s", exc)
        return {
            "severity": "medium",
            "summary": "Explanation unavailable — LLM error.",
            "probable_cause": str(exc),
            "recommendation": "Review sensor logs manually.",
        }


async def close():
    """Cleanly close the shared HTTP client on app shutdown."""
    await _client.aclose()
