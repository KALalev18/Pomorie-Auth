"""Seed a demo: generate history, let the processor work, simulate the authorities.

Assumes the compose services are up (the processor container does the processing).

    docker compose run --rm demo                      # inside compose
    python -m pomorie.demo --start 2026-06-01 --days 92
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, date, datetime, timedelta

from pomorie.db import connect
from pomorie.evaluation import evaluate
from pomorie.generator.run import publish_days
from pomorie.kafka import ensure_topics, make_producer
from pomorie.processing.ledger import accrue_pending_rewards
from pomorie.reference.paths import REPO_ROOT
from pomorie.simulation.authorities import simulate


def wait_until_processed(expected_reports: int, expected_outcomes: int, timeout_s: float) -> None:
    """Block until the processor has landed every event in raw or the dead-letter table."""
    deadline = time.monotonic() + timeout_s
    with connect(autocommit=True) as conn:
        while True:
            reports, outcomes = conn.execute(
                "SELECT (SELECT count(*) FROM raw.report_events)"
                " + (SELECT count(*) FROM raw.dead_letter WHERE kafka_topic LIKE 'reports%%'),"
                " (SELECT count(*) FROM raw.outcome_events)"
                " + (SELECT count(*) FROM raw.dead_letter WHERE kafka_topic LIKE 'authority%%')"
            ).fetchone() or (0, 0)
            if reports >= expected_reports and outcomes >= expected_outcomes:
                return
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"processed {reports}/{expected_reports} reports,"
                    f" {outcomes}/{expected_outcomes} outcomes"
                )
            time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--days", type=int, default=92)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()

    ensure_topics()
    started = time.monotonic()
    generated = publish_days(args.start, args.days)
    print(f"published {generated['events']} report events")
    wait_until_processed(generated["events"], 0, args.timeout)

    # Authorities act on the routed cases; a second pass collects fines issued in the first.
    start = datetime(args.start.year, args.start.month, args.start.day, tzinfo=UTC)
    until = start + timedelta(days=args.days + 30)
    producer, outcomes = make_producer(), 0
    for _ in range(2):
        with connect() as conn:
            counts = simulate(conn, producer, until)
        outcomes += sum(counts.values())
        print(f"authorities emitted {counts}")
        wait_until_processed(generated["events"], outcomes, args.timeout)

    with connect() as conn:
        accrue_pending_rewards(conn)
        conn.commit()
        print(json.dumps(evaluate(conn), indent=2, default=str))

    # Build the warehouse now, so the dashboard has data without waiting for the hourly
    # Dagster schedule.
    subprocess.run(
        ["dbt", "build", "--quiet"],
        cwd=REPO_ROOT / "dbt",
        env={**os.environ, "DBT_PROFILES_DIR": "."},
        check=True,
    )
    print("warehouse built (dbt build)")
    print(f"demo seeded in {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    main()
