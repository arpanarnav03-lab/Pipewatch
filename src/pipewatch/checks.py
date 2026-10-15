"""Data quality checks.

Every check is a pure function: records in, CheckResult out. No database or network access,
which keeps them trivial to unit test and to reuse across pipelines.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

PASS, FAIL = "pass", "fail"
CRITICAL, WARNING = "critical", "warning"

Record = dict[str, Any]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    severity: str
    observed: float | None
    threshold: str
    message: str

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or datetime to an aware UTC datetime, or None if impossible."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _kind(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "float"
    if isinstance(value, (str, datetime)):
        return "datetime" if parse_ts(value) is not None else "str"
    return type(value).__name__


_COMPATIBLE = {"float": {"float"}, "datetime": {"datetime"}, "str": {"str", "datetime"}}


def _result(name, ok, severity, observed, threshold, message) -> CheckResult:
    return CheckResult(name, PASS if ok else FAIL, severity, observed, threshold, message)


def check_schema(records: Sequence[Record], schema: dict[str, str]) -> CheckResult:
    """Detect schema drift: missing columns, unexpected columns, changed value types."""
    name, threshold = "schema_drift", "no missing, unexpected or retyped columns"
    if not records:
        return _result(name, True, CRITICAL, 0, threshold, "no records to inspect")

    seen: set[str] = set()
    retyped: dict[str, str] = {}
    for rec in records:
        seen.update(rec)
        for col, expected in schema.items():
            kind = _kind(rec.get(col))
            if kind is not None and kind not in _COMPATIBLE[expected]:
                retyped.setdefault(col, kind)

    missing = sorted(set(schema) - seen)
    unexpected = sorted(seen - set(schema))
    issues = len(missing) + len(unexpected) + len(retyped)
    parts = []
    if missing:
        parts.append(f"missing columns: {missing}")
    if unexpected:
        parts.append(f"unexpected columns: {unexpected}")
    if retyped:
        parts.append("type changes: " + ", ".join(f"{c} now {k}" for c, k in retyped.items()))
    return _result(name, issues == 0, CRITICAL, issues, threshold, "; ".join(parts) or "schema ok")


def check_null_rates(
    records: Sequence[Record],
    columns: Iterable[str],
    max_null_rate: dict[str, float],
    default: float,
) -> list[CheckResult]:
    if not records:
        return []
    results = []
    n = len(records)
    for col in columns:
        rate = sum(1 for r in records if r.get(col) is None) / n
        limit = max_null_rate.get(col, default)
        results.append(
            _result(
                f"null_rate:{col}",
                rate <= limit,
                CRITICAL,
                round(rate, 4),
                f"<= {limit:.0%}",
                f"{rate:.1%} of {col} values are null",
            )
        )
    return results


def check_duplicates(records: Sequence[Record], key: Sequence[str]) -> CheckResult:
    name, threshold = "duplicate_keys", "0 duplicate keys"
    unique = {tuple(str(r.get(k)) for k in key) for r in records}
    dupes = len(records) - len(unique)
    return _result(
        name, dupes == 0, WARNING, dupes, threshold, f"{dupes} duplicate rows on key {tuple(key)}"
    )


def check_volume(
    row_count: int, history: Sequence[int], max_drop: float = 0.30, min_history: int = 3
) -> CheckResult:
    """Fail if this batch is more than `max_drop` below the recent average batch size."""
    name = "row_count"
    if row_count == 0:
        return _result(name, False, CRITICAL, 0, "> 0 rows", "batch is empty")
    if len(history) < min_history:
        return _result(
            name, True, CRITICAL, row_count, "needs history",
            f"only {len(history)} prior runs; baseline not established yet",
        )  # fmt: skip
    baseline = mean(history)
    floor = baseline * (1 - max_drop)
    return _result(
        name,
        row_count >= floor,
        CRITICAL,
        row_count,
        f">= {floor:.0f} (7d avg {baseline:.0f} minus {max_drop:.0%})",
        f"{row_count} rows vs 7d average of {baseline:.0f}",
    )


def check_freshness(
    records: Sequence[Record], ts_field: str, max_lag: timedelta, now: datetime
) -> CheckResult:
    name, threshold = "freshness", f"newest record < {max_lag} old"
    stamps = [t for t in (parse_ts(r.get(ts_field)) for r in records) if t is not None]
    if not stamps:
        return _result(name, False, WARNING, None, threshold, f"no parseable {ts_field} values")
    lag = now - max(stamps)
    return _result(
        name, lag <= max_lag, WARNING, round(lag.total_seconds()), threshold,
        f"newest {ts_field} is {lag} old",
    )  # fmt: skip


def run_all(
    records: Sequence[Record],
    *,
    schema: dict[str, str],
    key: Sequence[str],
    timestamp_field: str,
    max_lag: timedelta,
    max_null_rate: dict[str, float],
    default_null_rate: float,
    history: Sequence[int],
    now: datetime,
) -> list[CheckResult]:
    results = [
        check_schema(records, schema),
        check_volume(len(records), history),
        check_duplicates(records, key),
        check_freshness(records, timestamp_field, max_lag, now),
    ]
    results.extend(check_null_rates(records, schema, max_null_rate, default_null_rate))
    return results
