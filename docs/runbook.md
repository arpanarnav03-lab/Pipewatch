# Runbook

Each section matches the `description` link on an alert in `observability/alert_rules.yml`.

Useful first commands (from `~/Desktop/pipewatch`):

```bash
curl -s "localhost:8000/runs?pipeline=weather&limit=5" | python3 -m json.tool
curl -s localhost:8000/runs/<run_id>/checks | python3 -m json.tool
docker compose logs --tail=50 app        # structured JSON, filter with: | grep '"status": "quarantined"'
```

## CriticalCheckFailed

**Meaning:** a critical check failed; the batch was quarantined and curated data is unchanged.

1. Find the run: `GET /runs?limit=5`, then `GET /runs/<run_id>/checks`; read the `message` of the failed check.
2. Inspect the raw batch: `SELECT payload FROM raw_events WHERE run_id = '<run_id>' LIMIT 20;`
3. By check:
   - `schema_drift`: upstream changed a column. Confirm against the source docs, then update `schema` in `pipelines.py` and the curated table if the change is intended.
   - `row_count`: partial or empty extract. Check the source status; trigger a re-run once it recovers.
   - `null_rate:<col>`: a field stopped populating upstream. Decide whether to raise that column's threshold or wait for a fix.
4. Re-run: `make run-once`. The alert clears when the next run passes.

## WarningCheckFailed

**Meaning:** data *was* loaded but looks suspicious (duplicates, or lag above the pipeline's `max_lag`).

- `duplicate_keys`: a batch repeated rows. Curated is safe (upserts on the key); investigate the source for double delivery.
- `freshness`: the newest record is older than allowed. Check whether the source is publishing late; see also DataStale.

## DataStale

**Meaning:** the newest event time in curated data is more than 2 hours old. This is the "silent failure" alert: runs may look healthy while the data is not moving.

1. Confirm the lag in Grafana (*Data lag* panel).
2. Was the latest run quarantined? If so, handle it as CriticalCheckFailed.
3. If runs succeed but the data is old, the source is serving stale data: contact the data owner.

## RowCountDrop

**Meaning:** rows fetched fell more than 30% below the 7-day average. The in-app `row_count` check normally quarantines this too; this Prometheus rule is an independent second signal.

1. Check the source for an outage or a changed query window.
2. Compare `rows_fetched` across recent runs in `GET /runs`.

## PipelineRunFailing

**Meaning:** the latest run was quarantined or crashed.

- `status = quarantined` → follow CriticalCheckFailed.
- `status = failed` → read the `error` field in `GET /runs`, and the stack trace in the logs (`pipeline_run_crashed`). Common causes: source API down (the fetch retries 3 times first), database unreachable.

## PipelineNotRunning

**Meaning:** no run has started for over 3 hours; the scheduler is stuck or the service is restarting in a loop.

1. `docker compose ps` and `docker compose logs --tail=100 app`.
2. `docker compose restart app`. The scheduler runs a pipeline immediately on startup.

## PipeWatchDown

**Meaning:** Prometheus cannot scrape the service.

1. `curl -s localhost:8000/healthz`: a 503 means the database is unreachable; check `docker compose ps postgres`.
2. Check the container: `docker compose ps app`, then its logs.
