"""Persistence. `PostgresRepository` is the real thing; tests use an in-memory stand-in."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from importlib import resources
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .checks import CheckResult, Record, parse_ts
from .pipelines import Pipeline


class Repository(Protocol):
    def init_schema(self) -> None: ...
    def ping(self) -> None: ...
    def start_run(
        self, run_id: UUID, pipeline: str, started_at: datetime, injected_fault: str | None
    ) -> None: ...
    def finish_run(
        self,
        run_id: UUID,
        *,
        status: str,
        finished_at: datetime,
        rows_fetched: int,
        rows_loaded: int,
        max_observed_at: datetime | None,
        error: str | None,
    ) -> None: ...
    def save_raw(self, run_id: UUID, pipeline: str, records: list[Record]) -> None: ...
    def save_results(
        self, run_id: UUID, pipeline: str, results: list[CheckResult], checked_at: datetime
    ) -> None: ...
    def load_curated(
        self, pipeline: Pipeline, run_id: UUID, records: list[Record], loaded_at: datetime
    ) -> int: ...
    def recent_row_counts(self, pipeline: str, since: datetime, limit: int = 200) -> list[int]: ...
    def list_runs(self, pipeline: str | None, limit: int) -> list[dict[str, Any]]: ...
    def get_checks(self, run_id: UUID) -> list[dict[str, Any]]: ...
    def save_alert(self, name: str, status: str, severity: str | None, payload: dict) -> None: ...


def _coerce(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "float":
        return float(value)
    if kind == "datetime":
        return parse_ts(value)
    return str(value)


class PostgresRepository:
    """Connection-per-operation: volumes here are tiny, and it avoids stale-connection bugs."""

    def __init__(self, database_url: str):
        self.url = database_url

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.url, row_factory=dict_row)

    def init_schema(self) -> None:
        ddl = resources.files("pipewatch").joinpath("schema.sql").read_text()
        with self._conn() as conn:
            conn.execute(ddl)

    def ping(self) -> None:
        with self._conn() as conn:
            conn.execute("SELECT 1")

    def start_run(self, run_id, pipeline, started_at, injected_fault) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, pipeline, started_at, status, injected_fault)"
                " VALUES (%s, %s, %s, 'running', %s)",
                (run_id, pipeline, started_at, injected_fault),
            )

    def finish_run(
        self, run_id, *, status, finished_at, rows_fetched, rows_loaded, max_observed_at, error
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE pipeline_runs SET status=%s, finished_at=%s, rows_fetched=%s,"
                " rows_loaded=%s, max_observed_at=%s, error=%s WHERE run_id=%s",
                (status, finished_at, rows_fetched, rows_loaded, max_observed_at, error, run_id),
            )

    def save_raw(self, run_id, pipeline, records) -> None:
        if not records:
            return
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw_events (run_id, pipeline, payload) VALUES (%s, %s, %s)",
                [(run_id, pipeline, json.dumps(r, default=str)) for r in records],
            )

    def save_results(self, run_id, pipeline, results, checked_at) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO dq_results (run_id, pipeline, check_name, status, severity,"
                " observed, threshold, message, checked_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (run_id, pipeline, r.name, r.status, r.severity, r.observed, r.threshold,
                     r.message, checked_at)
                    for r in results
                ],
            )  # fmt: skip

    def load_curated(self, pipeline, run_id, records, loaded_at) -> int:
        cols = list(pipeline.schema)
        latest: dict[tuple, Record] = {}
        for rec in records:  # last write wins within a batch
            latest[tuple(str(rec.get(k)) for k in pipeline.key)] = rec
        stmt = sql.SQL(
            "INSERT INTO {table} ({cols}, run_id, loaded_at) VALUES ({ph}, %s, %s) "
            "ON CONFLICT ({key}) DO UPDATE SET {upd}, run_id = EXCLUDED.run_id, "
            "loaded_at = EXCLUDED.loaded_at"
        ).format(
            table=sql.Identifier(pipeline.table),
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            ph=sql.SQL(", ").join(sql.Placeholder() * len(cols)),
            key=sql.SQL(", ").join(map(sql.Identifier, pipeline.key)),
            upd=sql.SQL(", ").join(
                sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
                for c in cols
                if c not in pipeline.key
            ),
        )
        rows = [
            tuple(_coerce(rec.get(c), pipeline.schema[c]) for c in cols) + (run_id, loaded_at)
            for rec in latest.values()
        ]
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(stmt, rows)
        return len(rows)

    def recent_row_counts(self, pipeline, since, limit=200) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT rows_fetched FROM pipeline_runs WHERE pipeline=%s AND status='success'"
                " AND injected_fault IS NULL AND started_at >= %s"
                " ORDER BY started_at DESC LIMIT %s",
                (pipeline, since, limit),
            ).fetchall()
        return [r["rows_fetched"] for r in rows]

    def list_runs(self, pipeline, limit) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM pipeline_runs WHERE (%s::text IS NULL OR pipeline=%s)"
                " ORDER BY started_at DESC LIMIT %s",
                (pipeline, pipeline, limit),
            ).fetchall()

    def get_checks(self, run_id) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT check_name, status, severity, observed, threshold, message, checked_at"
                " FROM dq_results WHERE run_id=%s ORDER BY id",
                (run_id,),
            ).fetchall()

    def save_alert(self, name, status, severity, payload) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO alerts_received (alert_name, status, severity, payload)"
                " VALUES (%s, %s, %s, %s)",
                (name, status, severity, json.dumps(payload, default=str)),
            )


BASELINE_WINDOW = timedelta(days=7)
