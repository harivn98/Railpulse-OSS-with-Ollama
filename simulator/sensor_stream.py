"""
RailPulse sensor simulator.

Generates synthetic railway telemetry for multiple track sections and
pushes batches to the FastAPI /telemetry/ingest endpoint every few seconds.

Usage:
    python -m simulator.sensor_stream

    # Or with custom settings:
    API_URL=http://localhost:8000 PUBLISH_INTERVAL=5 python -m simulator.sensor_stream

Sensor types and normal operating ranges:
  vibration    0 – 15 Hz    (spike: 40 – 80)
  temperature  15 – 45 °C   (spike: 70 – 110)
  speed        50 – 130 km/h
  axle_load    40 – 90 kN   (spike: 130 – 180)
"""

import asyncio
import logging
import math
import os
import random
from datetime import datetime, timezone

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

API_URL = os.getenv("API_URL", "http://localhost:8000")
PUBLISH_INTERVAL = float(os.getenv("PUBLISH_INTERVAL", "3"))   # seconds between batches
TRACK_SECTIONS = ["A1", "A2", "B1", "B2", "C1"]
SPIKE_PROBABILITY = 0.03  # 3 % chance any reading is an anomalous spike

SENSOR_CONFIG = {
    "vibration":   {"unit": "Hz",   "base": 7.0,  "amplitude": 4.0,  "noise": 1.5,  "spike_range": (45, 80)},
    "temperature": {"unit": "°C",   "base": 30.0, "amplitude": 8.0,  "noise": 2.0,  "spike_range": (75, 110)},
    "speed":       {"unit": "km/h", "base": 90.0, "amplitude": 20.0, "noise": 5.0,  "spike_range": None},
    "axle_load":   {"unit": "kN",   "base": 65.0, "amplitude": 15.0, "noise": 3.0,  "spike_range": (130, 180)},
}


class SectionState:
    """Tracks the phase angle for each section's sine wave so readings are continuous."""

    def __init__(self, section: str):
        self.section = section
        self.t = random.uniform(0, 2 * math.pi)  # random phase offset per section

    def next_reading(self, sensor_type: str) -> float:
        cfg = SENSOR_CONFIG[sensor_type]
        self.t += 0.15  # advance time

        value = cfg["base"] + cfg["amplitude"] * math.sin(self.t) + random.gauss(0, cfg["noise"])

        # Occasional spike injection to exercise the anomaly detector
        if cfg["spike_range"] and random.random() < SPIKE_PROBABILITY:
            low, high = cfg["spike_range"]
            value = random.uniform(low, high)
            logger.warning("Spike injected: section=%s sensor=%s value=%.2f", self.section, sensor_type, value)

        return round(value, 3)


async def run():
    states = {s: SectionState(s) for s in TRACK_SECTIONS}
    tick = 0

    async with httpx.AsyncClient(base_url=API_URL, timeout=10.0) as client:
        logger.info("Sensor simulator started — pushing to %s every %.1fs", API_URL, PUBLISH_INTERVAL)

        while True:
            now = datetime.now(timezone.utc)
            readings = []

            for section, state in states.items():
                for sensor_type, cfg in SENSOR_CONFIG.items():
                    readings.append(
                        {
                            "track_section": section,
                            "sensor_type": sensor_type,
                            "value": state.next_reading(sensor_type),
                            "unit": cfg["unit"],
                            "recorded_at": now.isoformat(),
                        }
                    )

            try:
                resp = await client.post("/telemetry/ingest", json={"readings": readings})
                resp.raise_for_status()
                tick += 1
                if tick % 10 == 0:
                    logger.info("Tick %d — published %d readings", tick, len(readings))
            except Exception as exc:
                logger.error("Failed to publish readings: %s", exc)

            await asyncio.sleep(PUBLISH_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
