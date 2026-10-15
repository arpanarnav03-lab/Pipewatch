# PipeWatch

**A data pipeline that monitors its own data quality.** It ingests data, validates every batch, quarantines bad data before it reaches consumers, exposes health metrics, and alerts when trust in the data drops.

Pipelines rarely crash; they fail *silently*. A job "succeeds" but loads half the rows, a column is renamed upstream, or the feed stops updating. PipeWatch is the reliability layer that notices.

```
 Source (Open-Meteo API | synthetic)
        │
  Ingestion (Python) ──► raw_events (Postgres, JSONB, every payload kept)
        │
  Data quality checks ──► dq_results (per check, with severity)
        │
   critical failure? ── yes ─► QUARANTINE: curated tables untouched
        │ no
        ▼
  weather_clean (typed, de-duplicated upsert)

  FastAPI service ──► /metrics ──► Prometheus ──► Alertmanager ──► webhook (Slack-ready)
        │                               │
   /runs, /checks                    Grafana
```

## What it checks

| Check | Catches | Severity |
|---|---|---|
| `schema_drift` | missing, unexpected or retyped columns | critical |
| `row_count` | empty batch, or >30% below the 7-day average | critical |
| `null_rate:<col>` | a column going null above its threshold | critical |
| `duplicate_keys` | the same natural key twice in a batch | warning |
| `freshness` | newest record older than the allowed lag | warning |

**Critical** failures quarantine the batch (raw data is kept for debugging; curated tables are never touched). **Warnings** load the data but raise an alert.

## Quickstart

Requires Docker.

```bash
cd ~/Desktop/pipewatch
cp .env.example .env          # then edit the passwords
make up
```

| Service | URL |
|---|---|
| API / docs | http://localhost:8000/docs |
| Grafana (dashboard: *PipeWatch: data trust*) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |

Grafana login is `admin` and the password from `GRAFANA_ADMIN_PASSWORD` in `.env`.

The default `PIPEWATCH_SOURCE=synthetic` needs no internet. Set `PIPEWATCH_SOURCE=open_meteo` for live weather data (free, no API key).

## Demo: break it on purpose

Let at least 3 clean runs accumulate first (the volume check needs a baseline; at the default 2-minute demo interval that takes about 6 minutes, or run `make run-once` a few times). Then:

```bash
make inject FAULT=schema      # column renamed + type change   -> quarantined, critical alert
make inject FAULT=volume      # partial extract (40% of rows)  -> quarantined, critical alert
make inject FAULT=nulls       # a sensor stops reporting       -> quarantined, critical alert
make inject FAULT=duplicate   # batch partly loaded twice      -> loaded, warning alert
make inject FAULT=late        # upstream 6 hours behind        -> loaded, warning + DataStale alert
make report                   # detection latency per injected fault
```

Watch the *Failed checks right now* panel in Grafana, then Alertmanager at :9093. Injected runs are excluded from the volume baseline, so repeated tests never normalise the failure.

## Development

```bash
cd ~/Desktop/pipewatch
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

make test                     # unit tests
make lint
make rules-test               # alert-rule unit tests (needs promtool)
```

To include the Postgres integration tests, point `TEST_DATABASE_URL` at any scratch database, for example one from `docker compose up -d postgres`:

```bash
export TEST_DATABASE_URL=postgresql://pipewatch:pipewatch@localhost:5432/pipewatch
make test
```

> The integration tests **truncate** PipeWatch's tables. Never point them at data you care about.

CI (GitHub Actions) runs lint, format check, tests with a Postgres service and a coverage gate, `promtool` checks and unit tests of the alert rules, `terraform fmt` and `validate`, and builds and publishes the image to GHCR on `main`.

## Deploying to AWS

`terraform/` provisions an encrypted RDS Postgres (private), an EC2 instance running the container, a Secrets Manager secret holding `DATABASE_URL` (the password is generated, never in code or state outputs), least-privilege IAM, IMDSv2 only, and security groups that expose the API to one CIDR.

```bash
cd ~/Desktop/pipewatch/terraform
cp terraform.tfvars.example terraform.tfvars   # set image and allowed_cidr
terraform init && terraform plan
terraform apply
```

This deploys the app and database only; the Prometheus/Grafana stack runs via Compose. Note the Terraform state contains the generated DB password, so use an encrypted remote backend for anything beyond a demo.

## Design decisions

- **Raw → curated layering.** Raw payloads are stored as JSONB exactly as received, so a drifted batch can be inspected and replayed without loss.
- **Quarantine over rollback.** Bad batches never reach curated tables, so consumers never see a half-loaded state.
- **Checks are pure functions** (records in, result out), so they are trivially unit-testable and reusable across pipelines.
- **Idempotent loads.** Curated writes are upserts on the natural key; re-running a batch is safe.
- **Metrics describe state; alert rules decide what is unhealthy.** Thresholds live in `observability/alert_rules.yml` and are themselves unit-tested.
- **Pipelines are declarative.** See [docs/adding-a-pipeline.md](docs/adding-a-pipeline.md).

## Repository layout

```
src/pipewatch/       checks, runner, db, metrics, API, sources, fault injection
tests/               unit + Postgres integration + mocked-HTTP tests
observability/       Prometheus, Alertmanager, alert-rule tests, Grafana provisioning
terraform/           AWS deployment
docs/                architecture, runbook, adding a pipeline, impact measurement
scripts/             detection-time report
```

## Known limitations

- Single-process scheduler (APScheduler); fine for this scale, not for HA. Airflow would be the next step for dependencies and backfills.
- Row-count baseline is a simple 7-day mean; it does not model weekly seasonality.
- The Terraform module has been syntax-checked but not applied against a live AWS account.
- Alert delivery defaults to a webhook back into the service; Slack is a few commented lines in `alertmanager.yml`.

## Stretch ideas

Go-based custom exporter, Loki log aggregation with error-pattern alerts, an LLM step that summarises failed checks into an incident note, Helm chart and Kubernetes deployment.
