import pytest

from pipewatch.injection import FAULTS, apply_fault
from pipewatch.pipelines import WEATHER
from pipewatch.runner import run_pipeline


def baseline(repo, settings, n=4):
    for _ in range(n):
        assert run_pipeline(WEATHER, repo, settings).status == "success"


def failed_names(summary):
    return {r.name for r in summary.results if r.failed}


def test_clean_run_loads_curated(repo, settings):
    s = run_pipeline(WEATHER, repo, settings)
    assert s.status == "success"
    assert s.rows_fetched == s.rows_loaded == 24 * len(settings.cities)
    assert not failed_names(s)
    assert len(repo.curated) == s.rows_loaded


def test_repeated_runs_are_idempotent(repo, settings):
    baseline(repo, settings)
    assert len(repo.curated) == 24 * len(settings.cities)


@pytest.mark.parametrize(
    ("fault", "expected_check", "status"),
    [
        ("schema", "schema_drift", "quarantined"),
        ("volume", "row_count", "quarantined"),
        ("nulls", "null_rate:humidity_pct", "quarantined"),
        ("duplicate", "duplicate_keys", "success"),  # warning only
        ("late", "freshness", "success"),  # warning only
    ],
)
def test_each_injected_fault_is_detected(repo, settings, fault, expected_check, status):
    baseline(repo, settings)
    s = run_pipeline(WEATHER, repo, settings, inject=fault)
    assert expected_check in failed_names(s)
    assert s.status == status


def test_quarantine_keeps_raw_but_protects_curated(repo, settings):
    baseline(repo, settings)
    curated_before = dict(repo.curated)
    raw_before = len(repo.raw)
    s = run_pipeline(WEATHER, repo, settings, inject="schema")
    assert s.status == "quarantined" and s.rows_loaded == 0
    assert repo.curated == curated_before
    assert len(repo.raw) == raw_before + s.rows_fetched


def test_injected_runs_do_not_poison_the_baseline(repo, settings):
    baseline(repo, settings)
    for _ in range(3):
        run_pipeline(WEATHER, repo, settings, inject="volume")
    # still detected on the 4th attempt: volume runs never entered the baseline
    assert "row_count" in failed_names(run_pipeline(WEATHER, repo, settings, inject="volume"))


def test_fetch_exception_is_recorded_as_failed(repo, settings):
    def boom(*_):
        raise ConnectionError("upstream down")

    broken = type(WEATHER)(**{**WEATHER.__dict__, "fetch": boom})
    s = run_pipeline(broken, repo, settings)
    assert s.status == "failed" and "upstream down" in s.error
    assert repo.runs[s.run_id]["status"] == "failed"


def test_unknown_fault_rejected():
    with pytest.raises(ValueError):
        apply_fault([], "nope")


def test_apply_fault_does_not_mutate_input(settings, now):
    from pipewatch.sources import synthetic_weather

    records = synthetic_weather(settings, now)
    snapshot = [dict(r) for r in records]
    for fault in FAULTS:
        apply_fault(records, fault)
    assert records == snapshot
