"""Report detection latency for injected faults.

For every run started with --inject, prints when the fault was injected (run start), when PipeWatch
first recorded a failed check, and when Alertmanager first notified us afterwards.

Usage: DATABASE_URL=... python scripts/detection_report.py
"""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

QUERY = """
SELECT r.injected_fault, r.status, r.started_at,
  (SELECT min(d.checked_at) FROM dq_results d
     WHERE d.run_id = r.run_id AND d.status = 'fail') AS detected_at,
  (SELECT min(a.received_at) FROM alerts_received a
     WHERE a.status = 'firing' AND a.received_at >= r.started_at) AS alerted_at
FROM pipeline_runs r
WHERE r.injected_fault IS NOT NULL
ORDER BY r.started_at
"""


def seconds(a, b):
    return f"{(b - a).total_seconds():7.1f}s" if a and b else "      -"


def main() -> None:
    url = os.environ.get(
        "DATABASE_URL", "postgresql://pipewatch:pipewatch@localhost:5432/pipewatch"
    )
    with psycopg.connect(url, row_factory=dict_row) as conn:
        rows = conn.execute(QUERY).fetchall()
    print(f"{'fault':<10} {'run status':<12} {'to check fail':>14} {'to alert':>10}")
    for r in rows:
        print(
            f"{r['injected_fault']:<10} {r['status']:<12} "
            f"{seconds(r['started_at'], r['detected_at']):>14} "
            f"{seconds(r['started_at'], r['alerted_at']):>10}"
        )
    print(
        "\nNote: 'to alert' is the first firing alert after the run, so run faults one at a time."
    )


if __name__ == "__main__":
    main()
