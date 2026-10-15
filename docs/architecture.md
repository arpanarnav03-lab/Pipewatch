# Architecture

## Run lifecycle

1. **Start**: a `pipeline_runs` row is written with status `running`, so even a crash leaves a trace.
2. **Fetch**: the pipeline's source returns records. Optional fault injection mutates the batch here.
3. **Raw store**: every record is saved to `raw_events` as JSONB, before any judgement.
4. **Validate**: pure check functions run over the batch; the volume check compares against the average of recent *successful, non-injected* runs (7-day window).
5. **Decide**: any failed *critical* check → status `quarantined` (curated untouched). Otherwise → upsert into the curated table, status `success`.
6. **Record**: results go to `dq_results`, the run row is finalised, Prometheus metrics are updated, and one structured JSON log line is emitted.
7. A fetch/DB exception is caught, recorded as status `failed`, and surfaces as `pipewatch_last_run_ok == 0`.

## Data model

| Table | Purpose |
|---|---|
| `pipeline_runs` | one row per run: status, row counts, newest event time, injected fault, error |
| `raw_events` | every payload as received (JSONB), keyed by `run_id` |
| `weather_clean` | curated, typed, de-duplicated; primary key `(city, observed_at)` |
| `dq_results` | one row per check per run: status, severity, observed value, threshold, message |
| `alerts_received` | notifications delivered by Alertmanager (enables detection-time measurement) |

## Metrics

| Metric | Meaning |
|---|---|
| `pipewatch_last_run_ok` | 1 if the latest run passed critical checks |
| `pipewatch_last_data_timestamp_seconds` | newest event time in curated data; `time() - x` is the data lag |
| `pipewatch_rows_fetched` / `pipewatch_rows_loaded` | batch size and rows promoted to curated |
| `pipewatch_check_failed{check,severity}` | 1 if that check failed in the latest run |
| `pipewatch_run_duration_seconds` | histogram of run durations |
| `pipewatch_runs_total{status}` | counter by outcome (feeds the data-trust percentage) |
| `pipewatch_last_run_timestamp_seconds` | detects a stalled scheduler |

The lag is computed in PromQL at query time rather than stored, so it keeps growing correctly even when no new run completes.

## Why these trade-offs

- **Connection per operation** in the repository: at one batch per hour, simplicity beats pooling, and it avoids stale-connection failures.
- **Quarantine, not delete**: bad data is evidence. Raw rows for a quarantined run remain queryable by `run_id`.
- **Warnings still load**: duplicates and slightly late data are suspicious, not corrupt; blocking them would trade a data-quality problem for an availability problem.
