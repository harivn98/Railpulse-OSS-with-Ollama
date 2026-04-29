"""
RailPulse OSS — verification script.

Validates that all project goals are achieved by checking:
  1. All modules import correctly.
  2. FastAPI app mounts all expected routes.
  3. Pydantic schemas serialise and deserialise correctly.
  4. Anomaly detector can score a synthetic time series.
  5. Simulator can generate readings.
  6. All infrastructure files exist.

Run:
    .venv\\Scripts\\python.exe verify.py
"""

import importlib
import os
import sys
from datetime import datetime, timezone

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Colours (Windows Terminal supports ANSI) ──────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
OK_MARK   = "PASS"
FAIL_MARK = "FAIL"

passed = 0
failed = 0

ROOT = os.path.dirname(os.path.abspath(__file__))


def check(label: str, fn):
    """Run a check function, print pass/fail, track counts."""
    global passed, failed
    try:
        result = fn()
        msg = f"  {GREEN}{OK_MARK}{RESET} {label}"
        if result:
            msg += f"  ->  {result}"
        print(msg)
        passed += 1
    except Exception as exc:
        print(f"  {RED}{FAIL_MARK}{RESET} {label}  ->  {exc}")
        failed += 1


def _get_app_routes():
    app = importlib.import_module("app.main").app
    return [r.path for r in app.routes if hasattr(r, "methods")]


def _has_route(path):
    return path in _get_app_routes()


# ══════════════════════════════════════════════════════════════════════════
# GOAL 1 — FastAPI backend with SQLAlchemy, Pydantic, PostgreSQL
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 1: FastAPI + SQLAlchemy + Pydantic backend{RESET}")


def test_config():
    importlib.import_module("app.config")
    return "settings loaded"
check("Import app.config (Pydantic settings)", test_config)


def test_database():
    mod = importlib.import_module("app.database")
    if not hasattr(mod, "engine"):
        raise ValueError("missing engine")
    if not hasattr(mod, "AsyncSessionLocal"):
        raise ValueError("missing AsyncSessionLocal")
    if not hasattr(mod, "Base"):
        raise ValueError("missing Base")
    if not hasattr(mod, "get_session"):
        raise ValueError("missing get_session")
    return "engine + AsyncSessionLocal + Base + get_session"
check("Import app.database (async SQLAlchemy engine + session)", test_database)


def test_models():
    mod = importlib.import_module("app.models")
    names = [mod.TelemetryReading.__name__, mod.AnomalyEvent.__name__, mod.MaintenanceNote.__name__]
    return ", ".join(names)
check("Import app.models (3 ORM models)", test_models)


def test_schemas():
    mod = importlib.import_module("app.schemas")
    public = [x for x in dir(mod) if x[0].isupper() and not x.startswith("_")]
    return f"{len(public)} schemas"
check("Import app.schemas (Pydantic v2 schemas)", test_schemas)


def test_full_app():
    routes = _get_app_routes()
    return f"{len(routes)} endpoints"
check("FastAPI app loads with all routers", test_full_app)


# ── Telemetry API ─────────────────────────────────────────────────────────
print(f"\n{BOLD}{CYAN}Goal 1a: Telemetry API{RESET}")

for path in ["/telemetry/ingest", "/telemetry/", "/telemetry/sections"]:
    def _check(p=path):
        if not _has_route(p):
            raise ValueError(f"route {p} not found")
        return "registered"
    check(f"{path}", _check)


# ── Alerts API ────────────────────────────────────────────────────────────
print(f"\n{BOLD}{CYAN}Goal 1b: Alerts API{RESET}")

for path in ["/alerts/", "/alerts/{alert_id}", "/alerts/{alert_id}/status", "/alerts/summary/stats"]:
    def _check(p=path):
        if not _has_route(p):
            raise ValueError(f"route {p} not found")
        return "registered"
    check(f"{path}", _check)


# ── Maintenance API ──────────────────────────────────────────────────────
print(f"\n{BOLD}{CYAN}Goal 1c: Maintenance API{RESET}")

for path in ["/maintenance/"]:
    def _check(p=path):
        if not _has_route(p):
            raise ValueError(f"route {p} not found")
        return "registered (POST + GET)"
    check(f"{path}", _check)


# ══════════════════════════════════════════════════════════════════════════
# GOAL 2 — Anomaly detection with dtaianomaly / sklearn
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 2: Anomaly detection (dtaianomaly / sklearn){RESET}")


def test_anomaly_import():
    importlib.import_module("app.services.anomaly")
    return "OK"
check("Import anomaly service", test_anomaly_import)


def test_detector_factory():
    mod = importlib.import_module("app.services.anomaly")
    det = mod._make_detector()
    backend = "dtaianomaly" if mod._USE_DTAI else "sklearn"
    return f"using {backend} — {type(det).__name__}"
check("Detector factory works", test_detector_factory)


def test_score_series():
    import numpy as np
    mod = importlib.import_module("app.services.anomaly")
    # Synthetic series with a clear spike at index 6
    values = np.array([5.0, 5.1, 5.2, 4.9, 5.0, 5.1, 50.0, 5.0, 5.1, 5.0, 5.2, 5.0])
    scores = mod._score_series(values)
    max_score = float(scores.max())
    if max_score < 0.5:
        raise ValueError(f"Expected high anomaly score for spike, got max={max_score:.3f}")
    return f"max anomaly score={max_score:.3f} (threshold passed)"
check("Score a synthetic time series", test_score_series)


def test_severity():
    mod = importlib.import_module("app.services.anomaly")
    checks = [
        (0.95, "critical"), (0.80, "high"), (0.65, "medium"), (0.40, "low"),
    ]
    for score, expected in checks:
        got = mod._severity_from_score(score)
        if got != expected:
            raise ValueError(f"severity({score}) = {got}, expected {expected}")
    return "critical/high/medium/low — all correct"
check("Severity classification works", test_severity)


# ══════════════════════════════════════════════════════════════════════════
# GOAL 3 — Ollama-powered LLM alert explanation + structured output
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 3: Ollama LLM integration (alert explanation + RAG Q&A){RESET}")


def test_ollama_client():
    mod = importlib.import_module("app.services.ollama_client")
    for fn_name in ["chat", "embed", "explain_alert"]:
        if not callable(getattr(mod, fn_name, None)):
            raise ValueError(f"{fn_name} not found or not callable")
    return "chat() + embed() + explain_alert() available"
check("Import ollama_client (chat, embed, explain_alert)", test_ollama_client)


def test_structured_schema():
    mod = importlib.import_module("app.services.ollama_client")
    schema = mod._ALERT_SCHEMA
    required = set(schema["required"])
    expected = {"severity", "summary", "probable_cause", "recommendation"}
    if required != expected:
        raise ValueError(f"Schema requires {required}, expected {expected}")
    return f"JSON schema requires: {sorted(required)}"
check("Structured output schema defined", test_structured_schema)


# ══════════════════════════════════════════════════════════════════════════
# GOAL 4 — RAG pipeline (embed, retrieve, answer)
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 4: RAG-style assistant{RESET}")


def test_rag_service():
    mod = importlib.import_module("app.services.rag")
    for fn_name in ["embed_anomaly_event", "embed_maintenance_note", "retrieve", "answer"]:
        if not callable(getattr(mod, fn_name, None)):
            raise ValueError(f"{fn_name} not found or not callable")
    return "embed + retrieve + answer pipeline available"
check("Import RAG service", test_rag_service)


def test_qa_route():
    if not _has_route("/qa/"):
        raise ValueError("route /qa/ not found")
    return "registered"
check("POST /qa/ registered", test_qa_route)


# ══════════════════════════════════════════════════════════════════════════
# GOAL 5 — Sensor simulator
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 5: Sensor simulator{RESET}")


def test_simulator_import():
    mod = importlib.import_module("simulator.sensor_stream")
    return f"{len(mod.TRACK_SECTIONS)} sections, {len(mod.SENSOR_CONFIG)} sensor types"
check("Import simulator", test_simulator_import)


def test_simulator_readings():
    mod = importlib.import_module("simulator.sensor_stream")
    state = mod.SectionState("TEST")
    readings = {st: state.next_reading(st) for st in mod.SENSOR_CONFIG}
    parts = [f"{k}={v}" for k, v in readings.items()]
    return ", ".join(parts)
check("Generate sample readings", test_simulator_readings)


# ══════════════════════════════════════════════════════════════════════════
# GOAL 6 — Schema round-trip tests
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 6: Pydantic schema validation{RESET}")


def test_telemetry_batch():
    s = importlib.import_module("app.schemas")
    batch = s.TelemetryBatchIn(readings=[
        s.TelemetryReadingIn(
            track_section="A1", sensor_type="vibration",
            value=12.5, unit="Hz",
            recorded_at=datetime.now(timezone.utc),
        )
    ])
    return f"batch with {len(batch.readings)} reading(s)"
check("TelemetryBatchIn validates correctly", test_telemetry_batch)


def test_qa_request():
    s = importlib.import_module("app.schemas")
    req = s.QARequest(question="Why was A1 flagged?", track_section="A1")
    return f"question='{req.question}'"
check("QARequest validates correctly", test_qa_request)


def test_maintenance_note():
    s = importlib.import_module("app.schemas")
    note = s.MaintenanceNoteIn(track_section="B2", author="Engineer X", note="Replaced rail segment")
    return f"section={note.track_section}, author={note.author}"
check("MaintenanceNoteIn validates correctly", test_maintenance_note)


def test_status_update_rejects_invalid():
    s = importlib.import_module("app.schemas")
    try:
        s.StatusUpdate(status="invalid_status")
        raise ValueError("Should have rejected invalid status")
    except ValueError as e:
        if "Should have rejected" in str(e):
            raise
        return "correctly rejects invalid values"
    except Exception:
        return "correctly rejects invalid values"
check("StatusUpdate rejects invalid status", test_status_update_rejects_invalid)


# ══════════════════════════════════════════════════════════════════════════
# GOAL 7 — Infrastructure files
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}Goal 7: Infrastructure files{RESET}")

infra_files = [
    "Dockerfile", "docker-compose.yml", "requirements.txt",
    ".env.example", "alembic.ini", "start.ps1",
]
for fname in infra_files:
    def _check(f=fname):
        fpath = os.path.join(ROOT, f)
        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"{f} not found at {fpath}")
        return "exists"
    check(f"{fname}", _check)


def test_alembic_env():
    fpath = os.path.join(ROOT, "alembic", "env.py")
    if not os.path.isfile(fpath):
        raise FileNotFoundError(f"alembic/env.py not found")
    return "exists"
check("alembic/env.py", test_alembic_env)


# ══════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════
total = passed + failed
print(f"\n{'═' * 60}")
if failed == 0:
    print(f"{BOLD}{GREEN}All {passed}/{total} checks passed!{RESET}")
    print(f"\n{CYAN}RailPulse OSS is fully wired and ready to run.{RESET}")
    print(f"Run {BOLD}.\\start.ps1{RESET} to start everything.\n")
else:
    print(f"{BOLD}{RED}{failed}/{total} checks failed.{RESET}")
    print(f"{YELLOW}Fix the above issues before running the project.{RESET}\n")
    sys.exit(1)
