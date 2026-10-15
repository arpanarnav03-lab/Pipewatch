"""Pipeline definitions. Adding a pipeline = adding a `Pipeline` here plus a curated table.

See docs/adding-a-pipeline.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .checks import Record
from .config import Settings
from .sources import fetch_weather


@dataclass(frozen=True)
class Pipeline:
    name: str
    table: str  # curated table, created in schema.sql
    schema: dict[str, str]  # column -> "str" | "float" | "datetime"
    key: tuple[str, ...]  # natural key used for upserts and duplicate detection
    timestamp_field: str  # event time, used for freshness
    fetch: Callable[[Settings, datetime], list[Record]]
    max_lag: timedelta = timedelta(hours=2)
    max_null_rate: dict[str, float] = field(default_factory=dict)
    default_null_rate: float = 0.05


WEATHER = Pipeline(
    name="weather",
    table="weather_clean",
    schema={
        "city": "str",
        "observed_at": "datetime",
        "temperature_c": "float",
        "humidity_pct": "float",
        "wind_kph": "float",
    },
    key=("city", "observed_at"),
    timestamp_field="observed_at",
    fetch=fetch_weather,
    max_lag=timedelta(hours=2),
)

PIPELINES: dict[str, Pipeline] = {p.name: p for p in (WEATHER,)}
