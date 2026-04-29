"""
RailPulse OSS — FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import Base, engine
from app.routers import alerts, maintenance, qa, telemetry
from app.services import anomaly as anomaly_service
from app.services import ollama_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---------- startup ----------
    logger.info("Creating database tables and enabling pgvector …")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Starting anomaly detection background task …")
    await anomaly_service.start_background_detector()

    yield

    # ---------- shutdown ----------
    logger.info("Stopping anomaly detection background task …")
    await anomaly_service.stop_background_detector()
    await ollama_client.close()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="RailPulse OSS",
    description=(
        "Open-source railway telemetry backend with dtaianomaly anomaly detection "
        "and Ollama-powered alert explanation and ops Q&A."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry.router)
app.include_router(alerts.router)
app.include_router(maintenance.router)
app.include_router(qa.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "version": app.version}
