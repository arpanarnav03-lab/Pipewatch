COMPOSE ?= docker compose
FAULT   ?= schema

.PHONY: help up down logs test lint fmt rules-test run-once inject report psql

help:           ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up:             ## Build and start the whole stack
	$(COMPOSE) up -d --build

down:           ## Stop the stack (add -v to the compose command to wipe data)
	$(COMPOSE) down

logs:           ## Follow app logs
	$(COMPOSE) logs -f app

test:           ## Unit tests (set TEST_DATABASE_URL to include Postgres integration tests)
	pytest --cov=pipewatch --cov-report=term-missing

lint:           ## Lint and format check
	ruff check . && ruff format --check .

fmt:            ## Auto-format
	ruff check --fix . && ruff format .

rules-test:     ## Unit-test the Prometheus alert rules (needs promtool)
	promtool test rules observability/alert_rules_test.yml

run-once:       ## Trigger one clean run in the running stack
	curl -s -X POST localhost:8000/pipelines/weather/run | python3 -m json.tool

inject:         ## Trigger a deliberately broken run: make inject FAULT=schema|late|duplicate|volume|nulls
	curl -s -X POST "localhost:8000/pipelines/weather/run?inject=$(FAULT)" | python3 -m json.tool

report:         ## Detection-time report for injected faults
	$(COMPOSE) exec -T app python - < scripts/detection_report.py

psql:           ## Open psql in the database container
	$(COMPOSE) exec postgres psql -U pipewatch pipewatch
