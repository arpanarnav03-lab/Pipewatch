from datetime import UTC, datetime, timedelta

import httpx
import pytest

from pipewatch import sources
from pipewatch.config import City, Settings

NOW = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)


def hourly_payload():
    """Open-Meteo style response: 48h of past+today data, including future hours."""
    start = datetime(2026, 1, 14, 0, 0)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(48)]
    n = len(times)
    return {
        "hourly": {
            "time": times,
            "temperature_2m": [10.0 + i for i in range(n)],
            "relative_humidity_2m": [50.0] * n,
            "wind_speed_10m": [5.0] * n,
        }
    }


@pytest.fixture
def one_city():
    return Settings(source="open_meteo", cities=(City("Testville", 1.0, 2.0),))


def patch_client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(
        sources.httpx, "Client", lambda: real(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(sources.time, "sleep", lambda _s: None)


def test_open_meteo_returns_exactly_the_last_24_hours(monkeypatch, one_city):
    patch_client(monkeypatch, lambda req: httpx.Response(200, json=hourly_payload()))
    records = sources.open_meteo_weather(one_city, NOW)
    assert len(records) == 24
    stamps = sorted(r["observed_at"] for r in records)
    assert stamps[-1].startswith("2026-01-15T12:00")  # newest hour not after "now"
    assert stamps[0].startswith("2026-01-14T13:00")
    assert set(records[0]) == {"city", "observed_at", "temperature_c", "humidity_pct", "wind_kph"}


def test_open_meteo_retries_transient_errors(monkeypatch, one_city):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=hourly_payload())

    patch_client(monkeypatch, handler)
    assert len(sources.open_meteo_weather(one_city, NOW)) == 24
    assert calls["n"] == 3


def test_open_meteo_gives_up_after_three_attempts(monkeypatch, one_city):
    patch_client(monkeypatch, lambda req: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        sources.open_meteo_weather(one_city, NOW)


def test_source_dispatch():
    assert len(sources.fetch_weather(Settings(source="synthetic"), NOW)) == 24 * 5
    with pytest.raises(ValueError):
        sources.fetch_weather(Settings(source="nope"), NOW)
