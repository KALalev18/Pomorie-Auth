"""Publish generated days to Redpanda, with labels and synthetic reporter identities.

The generator stands in for the API here (it produces the same contract), so historical
days can carry past timestamps. Everything downstream uses event time (received_at), so a
replayed month behaves exactly like a month that happened live.

    python -m pomorie.generator.run --start 2026-06-01 --days 60
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

import psycopg
from faker import Faker

from pomorie.config import get_settings
from pomorie.db import connect
from pomorie.generator.events import Generated, generate_day
from pomorie.generator.world import World, build_world
from pomorie.kafka import ensure_topics, make_producer

DEFAULT_SEED = 42


def register_reporters(conn: psycopg.Connection, world: World) -> int:
    """Synthetic identities (Faker, example.org e-mails). No real person is represented."""
    fake = Faker("bg_BG")
    fake.seed_instance(world.seed)
    rows = [
        (r.reporter_id, fake.name(), f"reporter{i:04d}@example.org")
        for i, r in enumerate(world.reporters)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO identity.reporters (reporter_id, display_name, email)"
            " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )
    return len(rows)


def write_labels(conn: psycopg.Connection, events: list[Generated]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO eval.report_labels (event_id, true_issue_id, scenario, is_abusive)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(g.event_id, g.true_issue_id, g.scenario, g.is_abusive) for g in events if g.event_id],
        )


def publish_days(start: date, days: int, seed: int = DEFAULT_SEED) -> dict[str, int]:
    ensure_topics()
    world = build_world(seed)
    producer = make_producer()
    topic = get_settings().reports_topic
    total = 0
    with connect() as conn:
        register_reporters(conn, world)
        for offset in range(days):
            events = generate_day(world, start + timedelta(days=offset))
            write_labels(conn, events)
            conn.commit()  # labels before events, so evaluation never misses one
            for g in events:
                producer.produce(topic, key=g.category, value=g.value)
                producer.poll(0)
            total += len(events)
    remaining = producer.flush(30)
    if remaining:
        raise RuntimeError(f"{remaining} events were not delivered")
    return {"days": days, "events": total}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    print(json.dumps(publish_days(args.start, args.days, args.seed)))


if __name__ == "__main__":
    main()
