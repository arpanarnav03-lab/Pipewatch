# Adding a new pipeline

Target: under 30 minutes. Everything downstream (checks, quarantine, metrics, alerts, dashboard panels) is generic and picks up the new pipeline automatically, because all metrics are labelled by `pipeline`.

## 1. Write the fetch function

In `src/pipewatch/sources.py`, add a function with signature `(settings, now) -> list[dict]` returning flat records:

```python
def fetch_orders(settings: Settings, now: datetime) -> list[Record]:
    ...
```

## 2. Create the curated table

Append to `src/pipewatch/schema.sql` (it is idempotent and applied at startup). Include a primary key on the natural key, plus `run_id UUID NOT NULL` and `loaded_at TIMESTAMPTZ NOT NULL`:

```sql
CREATE TABLE IF NOT EXISTS orders_clean (
    order_id    TEXT NOT NULL,
    placed_at   TIMESTAMPTZ NOT NULL,
    amount      DOUBLE PRECISION,
    run_id      UUID NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (order_id)
);
```

## 3. Declare the pipeline

In `src/pipewatch/pipelines.py`:

```python
ORDERS = Pipeline(
    name="orders",
    table="orders_clean",
    schema={"order_id": "str", "placed_at": "datetime", "amount": "float"},
    key=("order_id",),
    timestamp_field="placed_at",
    fetch=fetch_orders,
    max_lag=timedelta(hours=6),
    max_null_rate={"amount": 0.0},   # optional per-column overrides
)
PIPELINES = {p.name: p for p in (WEATHER, ORDERS)}
```

Column types are `"str"`, `"float"` or `"datetime"`. The schema you declare is the contract: any difference in an incoming batch is reported as drift.

## 4. Test it

Add a test beside `tests/test_runner.py` using `InMemoryRepository`: one clean run, then assert each fault you care about is detected. Fault injection in `injection.py` is written for the weather columns; extend `apply_fault` if your pipeline needs different mutations.

## 5. Tune the alerts

Per-pipeline freshness uses `max_lag` in code. The Prometheus `DataStale` rule uses a global 2-hour threshold; for a slower pipeline, add a rule with a `pipeline="orders"` matcher and the appropriate threshold, and add a case to `observability/alert_rules_test.yml`.

## 6. Document it

Add any pipeline-specific steps to `docs/runbook.md` under the relevant alert.
