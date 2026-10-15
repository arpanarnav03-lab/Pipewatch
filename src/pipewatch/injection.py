"""Deterministic fault injection, used to prove the checks and alerts actually work."""

from __future__ import annotations

import random
from datetime import timedelta

from .checks import Record, parse_ts

FAULTS = ("schema", "late", "duplicate", "volume", "nulls")


def apply_fault(records: list[Record], fault: str) -> list[Record]:
    if fault not in FAULTS:
        raise ValueError(f"unknown fault {fault!r}; choose from {FAULTS}")
    rng = random.Random(42)
    out = [dict(r) for r in records]

    if fault == "schema":  # a column is renamed and another changes type
        for r in out:
            if "wind_kph" in r:
                r["wind_speed"] = r.pop("wind_kph")
            if r.get("temperature_c") is not None:
                r["temperature_c"] = f"{r['temperature_c']:.1f}C"
    elif fault == "late":  # the upstream file is six hours behind
        for r in out:
            ts = parse_ts(r.get("observed_at"))
            if ts:
                r["observed_at"] = (ts - timedelta(hours=6)).isoformat()
    elif fault == "duplicate":  # a batch was loaded twice (half of it, at least)
        out += [dict(r) for r in rng.sample(out, k=len(out) // 2)]
    elif fault == "volume":  # upstream silently returned a partial extract
        out = out[: max(1, int(len(out) * 0.4))]
    elif fault == "nulls":  # a sensor stopped reporting
        for r in out:
            if rng.random() < 0.6:
                r["humidity_pct"] = None
    return out
