# RailPulse OSS

Open-source railway telemetry backend with local LLM-powered alert explanation and ops Q&A.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy (async) + asyncpg |
| Database | PostgreSQL 16 + pgvector |
| Anomaly detection | dtaianomaly (IsolationForest) |
| LLM runtime | Ollama (local, no cloud dependency) |
| Embeddings | Ollama `nomic-embed-text` via `/api/embed` |

## Architecture

```
Sensor Simulator
      │  POST /telemetry/ingest
      ▼
FastAPI Backend ────────────────────────────────────────┐
      │                                                 │
      ▼ (background, every 30 s)                        │
dtaianomaly ──anomaly scores──► Ollama /api/chat        │
                                 (alert explanation)    │
                                       │                │
                                       ▼                │
                              AnomalyEvent + embedding  │
                                   (pgvector)           │
                                                        │
POST /qa ──embed question──► pgvector cosine search     │
                                       │                │
                             top-k chunks + Ollama chat ◄┘
                                       │
                              Grounded answer + sources
```

## Quick start

### Prerequisites

- Docker + Docker Compose
- Ollama installed locally (or use the compose service)

### 1. Pull required Ollama models

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env if your Ollama is not on localhost:11434
```

### 3. Start services

```bash
docker compose up -d postgres ollama
# Then start the API (development mode with hot reload):
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Or run everything in Docker:

```bash
docker compose up --build
```

### 4. Run the sensor simulator

```bash
python -m simulator.sensor_stream
```

The simulator publishes batches of synthetic vibration, temperature, speed, and axle-load readings every 3 seconds across 5 track sections. It randomly injects anomalous spikes (3 % probability) to exercise the detection pipeline.

## API reference

### Telemetry

| Method | Path | Description |
|---|---|---|
| POST | `/telemetry/ingest` | Ingest a batch of sensor readings (≤ 500) |
| GET | `/telemetry/` | Query readings — filter by section, type, time range |
| GET | `/telemetry/sections` | List distinct track sections |

### Alerts

| Method | Path | Description |
|---|---|---|
| GET | `/alerts/` | List anomaly events (filter by section, severity, status) |
| GET | `/alerts/{id}` | Fetch single event with full LLM explanation |
| PATCH | `/alerts/{id}/status` | Transition to `acknowledged` or `resolved` |
| GET | `/alerts/summary/stats` | Count by severity and status |

### Maintenance

| Method | Path | Description |
|---|---|---|
| POST | `/maintenance/` | Create a note (auto-embedded for RAG) |
| GET | `/maintenance/` | List notes, filter by section |

### Q&A

| Method | Path | Description |
|---|---|---|
| POST | `/qa/` | Ask a natural-language question |

**Example Q&A request:**

```json
POST /qa/
{
  "question": "Why was Track Section A1 flagged yesterday?",
  "track_section": "A1"
}
```

**Example response:**

```json
{
  "answer": "Track Section A1 was flagged due to abnormal vibration readings ...",
  "sources": [
    {
      "source_type": "anomaly_event",
      "source_id": "...",
      "track_section": "A1",
      "snippet": "[Anomaly — vibration on A1, severity=high, 2025-01-15] ..."
    }
  ]
}
```

## Configuration

All settings are controlled via environment variables (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async PostgreSQL connection string |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_CHAT_MODEL` | `llama3.1:8b` | Model for alert explanation and Q&A |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Model for vector embeddings |
| `EMBED_DIM` | `768` | Embedding dimension (must match model output) |
| `ANOMALY_POLL_INTERVAL` | `30` | Seconds between detection sweeps |
| `ANOMALY_WINDOW_SIZE` | `60` | Readings per detection window |
| `ANOMALY_THRESHOLD` | `0.6` | Normalised score threshold (0–1) for raising events |
| `RAG_TOP_K` | `5` | Context chunks retrieved per Q&A query |

## Interactive docs

FastAPI auto-generates documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project structure

```
railpulse/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, router registration
│   ├── config.py               # Pydantic settings from environment
│   ├── database.py             # Async SQLAlchemy engine and session
│   ├── models.py               # ORM models (TelemetryReading, AnomalyEvent, MaintenanceNote)
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── routers/
│   │   ├── telemetry.py        # POST /ingest, GET /telemetry
│   │   ├── alerts.py           # GET/PATCH /alerts
│   │   ├── maintenance.py      # POST/GET /maintenance
│   │   └── qa.py               # POST /qa (RAG)
│   └── services/
│       ├── ollama_client.py    # Ollama HTTP client — chat + embed
│       ├── anomaly.py          # dtaianomaly background detection loop
│       └── rag.py              # Embed, retrieve, generate pipeline
├── simulator/
│   └── sensor_stream.py        # Synthetic telemetry publisher
├── alembic/                    # Database migrations
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## CV framing

> Built an open-source railway monitoring backend using **FastAPI**, **PostgreSQL + pgvector**, **dtaianomaly** for OSS time-series anomaly detection, and **Ollama** for local LLM-powered alert summarisation, semantic retrieval, and maintenance Q&A — with no cloud LLM dependency.
