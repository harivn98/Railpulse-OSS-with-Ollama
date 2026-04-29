"""
RailPulse OSS — application settings.

All values are loaded from environment variables with sensible defaults.
See `.env.example` for the full list.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://railpulse:railpulse@localhost:5432/railpulse"

    # ── Ollama ────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"
    embed_dim: int = 768

    # ── Anomaly detection ─────────────────────────────────────────────────
    anomaly_poll_interval: int = 30       # seconds between detection sweeps
    anomaly_window_size: int = 60         # readings per detection window
    anomaly_threshold: float = 0.6        # normalised score threshold (0–1)

    # ── RAG ───────────────────────────────────────────────────────────────
    rag_top_k: int = 5                    # context chunks per Q&A query

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
