"""Runs against a real Postgres. Skipped unless TEST_DATABASE_URL is set (CI sets it)."""

import os
from datetime import UTC

import pytest

from pipewatch.config import Settings
from pipewatch.db import PostgresRepository
from pipewatch.pipelines import WEATHER
from pipewatch.runner import run_pipeline

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def pg():
    repo = PostgresRepository(URL)
    repo.init_schema()
    with repo._conn() as conn:
        conn.execute(
            "TRUNCATE dq_results, raw_events, weather_clean, alerts_received, pipeline_runs CASCADE"
        )
    return repo


def test_schema_is_idempotent(pg):
    pg.init_schema()


def test_end_to_end_clean_then_faulty(pg):
    settings = Settings(source="synthetic")
    expected = 24 * len(settings.cities)
    for _ in range(4):
        assert run_pipeline(WEATHER, pg, settings).status == "success"
    with pg._conn() as conn:
        assert conn.execute("SELECT count(*) AS n FROM weather_clean").fetchone()["n"] == expected

    bad = run_pipeline(WEATHER, pg, settings, inject="schema")
    assert bad.status == "quarantined"
    with pg._conn() as conn:
        assert conn.execute("SELECT count(*) AS n FROM weather_clean").fetchone()["n"] == expected
        raw = conn.execute(
            "SELECT count(*) AS n FROM raw_events WHERE run_id=%s", (bad.run_id,)
        ).fetchone()["n"]
        assert raw == bad.rows_fetched
    failed = {c["check_name"] for c in pg.get_checks(bad.run_id) if c["status"] == "fail"}
    assert "schema_drift" in failed


def test_baseline_ignores_injected_and_failed_runs(pg):
    settings = Settings(source="synthetic")
    run_pipeline(WEATHER, pg, settings)
    run_pipeline(WEATHER, pg, settings, inject="volume")
    from datetime import datetime, timedelta

    counts = pg.recent_row_counts("weather", datetime.now(UTC) - timedelta(days=7))
    assert counts == [24 * len(settings.cities)]


def test_alert_roundtrip(pg):
    pg.save_alert("DataStale", "firing", "critical", {"x": 1})
    with pg._conn() as conn:
        assert (
            conn.execute("SELECT alert_name FROM alerts_received").fetchone()["alert_name"]
            == "DataStale"
        )
