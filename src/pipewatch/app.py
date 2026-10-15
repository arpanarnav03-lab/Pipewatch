"""FastAPI service: scheduler, health/inspection endpoints, /metrics, alert webhook."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import metrics
from .config import Settings
from .db import PostgresRepository, Repository
from .injection import FAULTS
from .logging_conf import configure_logging, log_event
from .pipelines import PIPELINES
from .runner import run_all_pipelines, run_pipeline

log = logging.getLogger("pipewatch.app")


def create_app(
    settings: Settings | None = None,
    repo: Repository | None = None,
    start_scheduler: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.repo = repo or PostgresRepository(settings.database_url)
        app.state.repo.init_schema()
        scheduler = None
        if start_scheduler:
            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(
                lambda: run_all_pipelines(app.state.repo, settings),
                "interval",
                minutes=settings.run_interval_minutes,
                next_run_time=datetime.now(UTC),
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="PipeWatch", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        try:
            app.state.repo.ping()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"database unavailable: {exc}") from exc
        return {"status": "ok"}

    @app.get("/metrics")
    def prometheus_metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/runs")
    def list_runs(pipeline: str | None = None, limit: int = Query(20, ge=1, le=200)):
        return app.state.repo.list_runs(pipeline, limit)

    @app.get("/runs/{run_id}/checks")
    def run_checks(run_id: UUID):
        return app.state.repo.get_checks(run_id)

    @app.get("/pipelines")
    def pipelines():
        out = []
        for name in PIPELINES:
            latest = app.state.repo.list_runs(name, 1)
            out.append({"pipeline": name, "latest_run": latest[0] if latest else None})
        return out

    @app.post("/pipelines/{name}/run")
    def trigger(name: str, inject: str | None = None):
        if name not in PIPELINES:
            raise HTTPException(404, f"unknown pipeline {name!r}")
        if inject and not settings.allow_fault_injection:
            raise HTTPException(403, "fault injection is disabled")
        if inject and inject not in FAULTS:
            raise HTTPException(422, f"inject must be one of {FAULTS}")
        return run_pipeline(PIPELINES[name], app.state.repo, settings, inject).as_dict()

    @app.post("/alerts/webhook")
    def alert_webhook(body: dict):
        """Alertmanager target. Records alerts so detection time can be measured."""
        for alert in body.get("alerts", []):
            labels = alert.get("labels", {})
            name, status = labels.get("alertname", "unknown"), alert.get("status", "unknown")
            metrics.ALERTS_RECEIVED.labels(name, status).inc()
            app.state.repo.save_alert(name, status, labels.get("severity"), alert)
            log_event(log, "alert_received", alertname=name, status=status, labels=labels)
        return {"received": len(body.get("alerts", []))}

    return app
