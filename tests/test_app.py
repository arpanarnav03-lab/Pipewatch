import pytest
from fastapi.testclient import TestClient

from pipewatch.app import create_app


@pytest.fixture
def client(repo, settings):
    with TestClient(create_app(settings, repo, start_scheduler=False)) as c:
        yield c


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_trigger_run_then_inspect(client):
    body = client.post("/pipelines/weather/run").json()
    assert body["status"] == "success"
    runs = client.get("/runs", params={"pipeline": "weather"}).json()
    assert len(runs) == 1
    assert client.get(f"/runs/{body['run_id']}/checks").status_code == 200
    assert client.get("/pipelines").json()[0]["latest_run"] is not None


def test_metrics_exposed_after_run(client):
    client.post("/pipelines/weather/run")
    text = client.get("/metrics").text
    for name in (
        "pipewatch_rows_fetched",
        "pipewatch_last_data_timestamp_seconds",
        "pipewatch_check_failed",
        "pipewatch_run_duration_seconds_bucket",
    ):
        assert name in text


def test_unknown_pipeline_and_bad_fault(client):
    assert client.post("/pipelines/nope/run").status_code == 404
    assert client.post("/pipelines/weather/run", params={"inject": "bogus"}).status_code == 422


def test_fault_injection_can_be_disabled(repo, settings):
    from dataclasses import replace

    locked = replace(settings, allow_fault_injection=False)
    with TestClient(create_app(locked, repo, start_scheduler=False)) as c:
        assert c.post("/pipelines/weather/run", params={"inject": "schema"}).status_code == 403


def test_alert_webhook_records_alerts(client, repo):
    payload = {
        "alerts": [
            {"status": "firing", "labels": {"alertname": "DataStale", "severity": "critical"}}
        ]
    }
    assert client.post("/alerts/webhook", json=payload).json() == {"received": 1}
    assert repo.alerts == [("DataStale", "firing", "critical")]
