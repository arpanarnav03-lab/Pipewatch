from datetime import timedelta

from pipewatch import checks

SCHEMA = {"city": "str", "observed_at": "datetime", "temperature_c": "float"}


def rec(**kw):
    base = {"city": "Tokyo", "observed_at": "2026-01-15T12:00:00+00:00", "temperature_c": 20.0}
    return base | kw


def test_schema_ok():
    assert not checks.check_schema([rec()], SCHEMA).failed


def test_schema_detects_missing_unexpected_and_retyped():
    bad = [
        {"city": "Tokyo", "observed_at": "2026-01-15T12:00:00Z", "temp": 1, "temperature_c": "20C"}
    ]
    r = checks.check_schema(bad, SCHEMA)
    assert r.failed and r.severity == checks.CRITICAL
    assert "unexpected columns: ['temp']" in r.message
    assert "temperature_c now str" in r.message


def test_schema_reports_missing_column():
    r = checks.check_schema([{"city": "Tokyo", "observed_at": "2026-01-15T12:00:00Z"}], SCHEMA)
    assert r.failed and "missing columns: ['temperature_c']" in r.message


def test_null_rate_threshold():
    records = [rec(temperature_c=None)] + [rec() for _ in range(9)]  # 10% null
    (strict,) = checks.check_null_rates(records, ["temperature_c"], {}, 0.05)
    (lenient,) = checks.check_null_rates(records, ["temperature_c"], {"temperature_c": 0.2}, 0.05)
    assert strict.failed and not lenient.failed


def test_duplicates_counted_on_key():
    records = [rec(), rec(), rec(city="London")]
    r = checks.check_duplicates(records, ("city", "observed_at"))
    assert r.failed and r.observed == 1 and r.severity == checks.WARNING


def test_volume_empty_batch_fails():
    assert checks.check_volume(0, [100] * 5).failed


def test_volume_needs_baseline_before_judging():
    assert not checks.check_volume(10, [100, 100]).failed


def test_volume_drop_boundary():
    history = [100] * 7
    assert not checks.check_volume(70, history).failed  # exactly -30%
    assert checks.check_volume(69, history).failed


def test_freshness(now):
    fresh = [rec(observed_at=(now - timedelta(minutes=30)).isoformat())]
    stale = [rec(observed_at=(now - timedelta(hours=5)).isoformat())]
    assert not checks.check_freshness(fresh, "observed_at", timedelta(hours=2), now).failed
    assert checks.check_freshness(stale, "observed_at", timedelta(hours=2), now).failed


def test_freshness_unparseable_timestamps_fail(now):
    assert checks.check_freshness(
        [rec(observed_at="garbage")], "observed_at", timedelta(hours=2), now
    ).failed


def test_parse_ts_treats_naive_as_utc():
    assert checks.parse_ts("2026-01-15T10:00").utcoffset() == timedelta(0)
