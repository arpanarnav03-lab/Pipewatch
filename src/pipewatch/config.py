"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

# name:latitude:longitude, separated by semicolons
DEFAULT_CITIES = (
    "Bengaluru:12.97:77.59;London:51.51:-0.13;New York:40.71:-74.01;"
    "Tokyo:35.68:139.69;Sydney:-33.87:151.21"
)


@dataclass(frozen=True)
class City:
    name: str
    latitude: float
    longitude: float


def parse_cities(raw: str) -> tuple[City, ...]:
    cities = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        name, lat, lon = part.split(":")
        cities.append(City(name.strip(), float(lat), float(lon)))
    return tuple(cities)


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://pipewatch:pipewatch@localhost:5432/pipewatch"
    source: str = "synthetic"  # synthetic | open_meteo
    run_interval_minutes: int = 60
    allow_fault_injection: bool = False
    log_level: str = "INFO"
    cities: tuple[City, ...] = parse_cities(DEFAULT_CITIES)

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL", cls.database_url),
            source=env.get("PIPEWATCH_SOURCE", cls.source),
            run_interval_minutes=int(env.get("PIPEWATCH_RUN_INTERVAL_MINUTES", "60")),
            allow_fault_injection=env.get("PIPEWATCH_ALLOW_FAULT_INJECTION", "false").lower()
            == "true",
            log_level=env.get("PIPEWATCH_LOG_LEVEL", cls.log_level),
            cities=parse_cities(env.get("PIPEWATCH_CITIES", DEFAULT_CITIES)),
        )
