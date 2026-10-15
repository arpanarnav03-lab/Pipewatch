-- Idempotent: applied at service start-up.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          UUID PRIMARY KEY,
    pipeline        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running', 'success', 'quarantined', 'failed')),
    rows_fetched    INT NOT NULL DEFAULT 0,
    rows_loaded     INT NOT NULL DEFAULT 0,
    max_observed_at TIMESTAMPTZ,
    injected_fault  TEXT,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_pipeline_started ON pipeline_runs (pipeline, started_at DESC);

-- Raw layer: every payload exactly as received, so bad batches can be inspected and replayed.
CREATE TABLE IF NOT EXISTS raw_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID NOT NULL REFERENCES pipeline_runs (run_id),
    pipeline    TEXT NOT NULL,
    payload     JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_raw_run ON raw_events (run_id);

-- Curated layer: typed, de-duplicated, only populated from batches that passed critical checks.
CREATE TABLE IF NOT EXISTS weather_clean (
    city          TEXT NOT NULL,
    observed_at   TIMESTAMPTZ NOT NULL,
    temperature_c DOUBLE PRECISION,
    humidity_pct  DOUBLE PRECISION,
    wind_kph      DOUBLE PRECISION,
    run_id        UUID NOT NULL,
    loaded_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (city, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_weather_observed ON weather_clean (observed_at DESC);

CREATE TABLE IF NOT EXISTS dq_results (
    id         BIGSERIAL PRIMARY KEY,
    run_id     UUID NOT NULL REFERENCES pipeline_runs (run_id),
    pipeline   TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('pass', 'fail')),
    severity   TEXT NOT NULL CHECK (severity IN ('critical', 'warning')),
    observed   DOUBLE PRECISION,
    threshold  TEXT,
    message    TEXT,
    checked_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_run ON dq_results (run_id);
CREATE INDEX IF NOT EXISTS idx_dq_failed ON dq_results (pipeline, checked_at DESC) WHERE status = 'fail';

CREATE TABLE IF NOT EXISTS alerts_received (
    id          BIGSERIAL PRIMARY KEY,
    alert_name  TEXT NOT NULL,
    status      TEXT NOT NULL,
    severity    TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB
);
