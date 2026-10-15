# Measuring impact

Fill this in from your own runs. The numbers below are deliberately blank: report what you measure, not what you expect.

## Method

1. Run the stack until at least 5 clean runs exist.
2. Inject each fault **one at a time**, waiting for its alert to resolve between runs:
   `make inject FAULT=<schema|volume|nulls|duplicate|late>`
3. Run `make report`. *To check fail* is the time from the run starting to the first recorded failed check; *to alert* is the time to the first notification Alertmanager delivered.
4. For the manual baseline, state your assumption explicitly. For example: "without PipeWatch the first signal is a stakeholder noticing a wrong dashboard; assume the next working-day morning check." A defensible baseline beats an impressive one.

## Results

| Fault | Detected by | Time to check fail | Time to alert | Manual baseline (state assumption) |
|---|---|---|---|---|
| schema | `schema_drift` | _measure_ | _measure_ | _state_ |
| volume | `row_count` | _measure_ | _measure_ | _state_ |
| nulls | `null_rate:humidity_pct` | _measure_ | _measure_ | _state_ |
| duplicate | `duplicate_keys` | _measure_ | _measure_ | _state_ |
| late | `freshness` / `DataStale` | _measure_ | _measure_ | _state_ |

## Other metrics worth reporting

- **Manual checks automated:** count of checks per pipeline (`SELECT count(DISTINCT check_name) FROM dq_results WHERE pipeline = 'weather'`).
- **Data trust:** share of runs that passed critical checks over a window (the Grafana stat panel, or `SELECT status, count(*) FROM pipeline_runs GROUP BY 1`). Exclude injected runs when you quote it.
- **Onboarding time:** how long adding a second pipeline took you, following `docs/adding-a-pipeline.md`.
- **Test coverage:** from `make test`.
