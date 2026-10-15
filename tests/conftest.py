from __future__ import annotations

from datetime import datetime

import pytest

from pipewatch.config import Settings
from pipewatch.pipelines import Pipeline


class InMemoryRepository:
    """Implements the Repository protocol without a database."""

    def __init__(self):
        self.runs: dict = {}
        self.raw: list = []
        self.results: list = []
        self.curated: dict = {}
        self.alerts: list = []

    def init_schema(self): ...
    def ping(self): ...

    def start_run(self, run_id, pipeline, started_at, injected_fault):
        self.runs[run_id] = {
            "run_id": run_id, "pipeline": pipeline, "started_at": started_at,
            "status": "running", "injected_fault": injected_fault, "rows_fetched": 0,
        }  # fmt: skip

    def finish_run(self, run_id, *, status, finished_at, rows_fetched, rows_loaded,
                   max_observed_at, error):  # fmt: skip
        self.runs[run_id].update(
            status=status, finished_at=finished_at, rows_fetched=rows_fetched,
            rows_loaded=rows_loaded, max_observed_at=max_observed_at, error=error,
        )  # fmt: skip

    def save_raw(self, run_id, pipeline, records):
        self.raw.extend((run_id, r) for r in records)

    def save_results(self, run_id, pipeline, results, checked_at):
        self.results.extend((run_id, r) for r in results)

    def load_curated(self, pipeline: Pipeline, run_id, records, loaded_at):
        for r in records:
            self.curated[tuple(str(r.get(k)) for k in pipeline.key)] = r
        return len({tuple(str(r.get(k)) for k in pipeline.key) for r in records})

    def recent_row_counts(self, pipeline, since, limit=200):
        return [
            r["rows_fetched"] for r in self.runs.values()
            if r["pipeline"] == pipeline and r["status"] == "success"
            and r["injected_fault"] is None and r["started_at"] >= since
        ][:limit]  # fmt: skip

    def list_runs(self, pipeline, limit):
        runs = [r for r in self.runs.values() if pipeline in (None, r["pipeline"])]
        return sorted(runs, key=lambda r: r["started_at"], reverse=True)[:limit]

    def get_checks(self, run_id):
        return [r.__dict__ | {"check_name": r.name} for rid, r in self.results if rid == run_id]

    def save_alert(self, name, status, severity, payload):
        self.alerts.append((name, status, severity))


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def settings():
    return Settings(source="synthetic", allow_fault_injection=True)


@pytest.fixture
def now():
    return datetime.fromisoformat("2026-01-15T12:30:00+00:00")
