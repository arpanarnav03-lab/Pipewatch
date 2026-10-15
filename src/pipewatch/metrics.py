"""Prometheus metrics. Gauges carry the *latest* state; alert rules decide what is unhealthy."""

from __future__ import annotations

from datetime import datetime

from prometheus_client import Counter, Gauge, Histogram

L = ["pipeline"]

RUNS_TOTAL = Counter("pipewatch_runs_total", "Pipeline runs by outcome", L + ["status"])
RUN_DURATION = Histogram(
    "pipewatch_run_duration_seconds", "Wall-clock duration of a pipeline run", L,
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)  # fmt: skip
LAST_RUN_DURATION = Gauge("pipewatch_last_run_duration_seconds", "Duration of the latest run", L)
LAST_RUN_OK = Gauge("pipewatch_last_run_ok", "1 if the latest run passed critical checks", L)
LAST_RUN_TS = Gauge("pipewatch_last_run_timestamp_seconds", "Start time of the latest run", L)
LAST_SUCCESS_TS = Gauge("pipewatch_last_success_timestamp_seconds", "Latest successful run", L)
ROWS_FETCHED = Gauge("pipewatch_rows_fetched", "Rows fetched by the latest run", L)
ROWS_LOADED = Gauge("pipewatch_rows_loaded", "Rows loaded to curated by the latest run", L)
DATA_TIMESTAMP = Gauge(
    "pipewatch_last_data_timestamp_seconds",
    "Newest event time in curated data. `time() - this` is the data lag.",
    L,
)
CHECK_FAILED = Gauge(
    "pipewatch_check_failed", "1 if the check failed in the latest run", L + ["check", "severity"]
)
CHECKS_TOTAL = Counter("pipewatch_checks_total", "Check evaluations", L + ["check", "status"])
ALERTS_RECEIVED = Counter(
    "pipewatch_alerts_received_total", "Alertmanager notifications", ["alertname", "status"]
)


def record_run(summary) -> None:  # summary: runner.RunSummary
    p = summary.pipeline
    RUNS_TOTAL.labels(p, summary.status).inc()
    RUN_DURATION.labels(p).observe(summary.duration_s)
    LAST_RUN_DURATION.labels(p).set(summary.duration_s)
    LAST_RUN_TS.labels(p).set(summary.started_at.timestamp())
    LAST_RUN_OK.labels(p).set(1 if summary.status == "success" else 0)
    ROWS_FETCHED.labels(p).set(summary.rows_fetched)
    ROWS_LOADED.labels(p).set(summary.rows_loaded)
    if summary.status == "success":
        LAST_SUCCESS_TS.labels(p).set(summary.started_at.timestamp())
    if summary.rows_loaded and summary.max_observed_at is not None:
        _set_data_ts(p, summary.max_observed_at)
    for r in summary.results:
        CHECK_FAILED.labels(p, r.name, r.severity).set(1 if r.failed else 0)
        CHECKS_TOTAL.labels(p, r.name, r.status).inc()


def _set_data_ts(pipeline: str, ts: datetime) -> None:
    DATA_TIMESTAMP.labels(pipeline).set(ts.timestamp())
