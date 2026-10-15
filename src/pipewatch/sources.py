"""Data sources. `synthetic` works offline; `open_meteo` hits a free public API (no key)."""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta

import httpx

from .checks import Record
from .config import Settings

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WINDOW_HOURS = 24


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def synthetic_weather(settings: Settings, now: datetime) -> list[Record]:
    """24 hourly readings per city, reproducible for a given hour."""
    records: list[Record] = []
    end = _floor_hour(now)
    for city in settings.cities:
        for i in range(WINDOW_HOURS):
            ts = end - timedelta(hours=i)
            rng = random.Random(f"{city.name}-{ts.isoformat()}")
            diurnal = math.sin((ts.hour - 9) / 24 * 2 * math.pi)
            records.append(
                {
                    "city": city.name,
                    "observed_at": ts.isoformat(),
                    "temperature_c": round(20 + 8 * diurnal + rng.gauss(0, 0.8), 2),
                    "humidity_pct": round(
                        min(100, max(10, 60 - 20 * diurnal + rng.gauss(0, 3))), 1
                    ),
                    "wind_kph": round(abs(12 + rng.gauss(0, 4)), 1),
                }
            )
    return records


def _get_with_retry(client: httpx.Client, params: dict, attempts: int = 3) -> dict:
    for attempt in range(1, attempts + 1):
        try:
            resp = client.get(OPEN_METEO_URL, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            if attempt == attempts:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def open_meteo_weather(settings: Settings, now: datetime) -> list[Record]:
    """Last 24 hourly observations per city from Open-Meteo."""
    from .checks import parse_ts

    records: list[Record] = []
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    with httpx.Client() as client:
        for city in settings.cities:
            data = _get_with_retry(
                client,
                {
                    "latitude": city.latitude,
                    "longitude": city.longitude,
                    "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                    "past_days": 1,
                    "forecast_days": 1,
                    "timezone": "UTC",
                    "wind_speed_unit": "kmh",
                },
            )
            h = data["hourly"]
            for t, temp, hum, wind in zip(
                h["time"], h["temperature_2m"], h["relative_humidity_2m"], h["wind_speed_10m"],
                strict=True,
            ):  # fmt: skip
                ts = parse_ts(t)
                if ts is not None and cutoff < ts <= now:
                    records.append(
                        {
                            "city": city.name,
                            "observed_at": ts.isoformat(),
                            "temperature_c": temp,
                            "humidity_pct": hum,
                            "wind_kph": wind,
                        }
                    )
    return records


def fetch_weather(settings: Settings, now: datetime) -> list[Record]:
    if settings.source == "open_meteo":
        return open_meteo_weather(settings, now)
    if settings.source == "synthetic":
        return synthetic_weather(settings, now)
    raise ValueError(f"unknown PIPEWATCH_SOURCE {settings.source!r}")
