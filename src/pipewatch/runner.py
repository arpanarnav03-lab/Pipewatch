"""One pipeline run: fetch -> store raw -> validate -> (promote to curated | quarantine)."""

from __future__ import annotations

import argparse
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import metrics
from .checks import CRITICAL, CheckResult, parse_ts, run_all
from .config import Settings
from .db import BASELINE_WINDOW, PostgresRepository, Repository
from .injection import FAULTS, apply_fault
from .logging_conf import configure_logging, log_event
from .pipelines import PIPELINES, Pipeline

log = logging.getLogger("pipewatch.runner")


@dataclass
class RunSummary:
    run_id: uuid.UUID
    pipeline: str
    status: str  # success | quarantined | failed
    started_at: datetime
    duration_s: float
    rows_fetched: int = 0
    rows_loaded: int = 0
    max_observed_at: datetime | None = None
    injected_fault: str | None = None
    error: str | None = None
    results: list[CheckResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "run_id": str(self.run_id),
            "pipeline": self.pipeline,
            "status": self.status,
            "rows_fetched": self.rows_fetched,
            "rows_loaded": self.rows_loaded,
            "duration_s": round(self.duration_s, 3),
            "injected_fault": self.injected_fault,
            "error": self.error,
            "failed_checks": [
                {"check": r.name, "severity": r.severity, "message": r.message}
                for r in self.results
                if r.failed
            ],
        }


def run_pipeline(
    pipeline: Pipeline, repo: Repository, settings: Settings, inject: str | None = None
) -> RunSummary:
    run_id = uuid.uuid4()
    started = datetime.now(UTC)
    t0 = time.monotonic()
    repo.start_run(run_id, pipeline.name, started, inject)
    summary = RunSummary(run_id, pipeline.name, "failed", started, 0.0, injected_fault=inject)

    try:
        records = pipeline.fetch(settings, started)
        if inject:
            records = apply_fault(records, inject)
        summary.rows_fetched = len(records)
        repo.save_raw(run_id, pipeline.name, records)

        history = repo.recent_row_counts(pipeline.name, started - BASELINE_WINDOW)
        summary.results = run_all(
            records,
            schema=pipeline.schema,
            key=pipeline.key,
            timestamp_field=pipeline.timestamp_field,
            max_lag=pipeline.max_lag,
            max_null_rate=pipeline.max_null_rate,
            default_null_rate=pipeline.default_null_rate,
            history=history,
            now=started,
        )
        stamps = [parse_ts(r.get(pipeline.timestamp_field)) for r in records]
        summary.max_observed_at = max((s for s in stamps if s), default=None)

        if any(r.failed and r.severity == CRITICAL for r in summary.results):
            summary.status = "quarantined"  # raw is kept, curated is untouched
        else:
            summary.rows_loaded = repo.load_curated(pipeline, run_id, records, started)
            summary.status = "success"
    except Exception as exc:  # noqa: BLE001 - a failed run must still be recorded and alerted on
        summary.status, summary.error = "failed", f"{type(exc).__name__}: {exc}"
        log.exception("pipeline_run_crashed", extra={"pipeline": pipeline.name})

    summary.duration_s = time.monotonic() - t0
    finished = datetime.now(UTC)
    if summary.results:
        repo.save_results(run_id, pipeline.name, summary.results, finished)
    repo.finish_run(
        run_id,
        status=summary.status,
        finished_at=finished,
        rows_fetched=summary.rows_fetched,
        rows_loaded=summary.rows_loaded,
        max_observed_at=summary.max_observed_at,
        error=summary.error,
    )
    metrics.record_run(summary)
    log_event(
        log, "pipeline_run_finished",
        level=logging.INFO if summary.status == "success" else logging.WARNING,
        **summary.as_dict(),
    )  # fmt: skip
    return summary


def run_all_pipelines(repo: Repository, settings: Settings) -> list[RunSummary]:
    return [run_pipeline(p, repo, settings) for p in PIPELINES.values()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a PipeWatch pipeline once.")
    parser.add_argument("--pipeline", default="weather", choices=sorted(PIPELINES))
    parser.add_argument("--inject", choices=FAULTS, help="deliberately break this run")
    args = parser.parse_args()

    settings = Settings.from_env()
    configure_logging(settings.log_level)
    repo = PostgresRepository(settings.database_url)
    repo.init_schema()
    summary = run_pipeline(PIPELINES[args.pipeline], repo, settings, inject=args.inject)
    print(json.dumps(summary.as_dict(), indent=2))


if __name__ == "__main__":
    main()
