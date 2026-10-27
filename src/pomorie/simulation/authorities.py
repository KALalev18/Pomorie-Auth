"""Simulated authorities: decide routed cases and collect fines, as outcome events.

The simulator plays reality, so unlike the pipeline it may read the generator's ground
truth (``eval``): an inspector on site would see that a spam report describes nothing.

Every decision is a pure function of the case id, and event ids are UUIDv5 of
(case, outcome). Running the simulator twice emits identical events, which the processor
recognises as duplicate deliveries.

    python -m pomorie.simulation.authorities --until 2026-08-31T23:59:59+00:00
"""

from __future__ import annotations

import argparse
import json
import math
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from confluent_kafka import Producer

from pomorie.config import get_settings
from pomorie.db import connect
from pomorie.kafka import ensure_topics, make_producer

NAMESPACE = uuid.UUID("5b0c3f0e-7f1d-4d8e-9a59-0c7e2c1f9a01")

# Median decision time as a share of the SLA. Above ~1 means most cases breach it.
SPEED = {
    "traffic_police": 0.45,
    "police": 0.7,
    "municipality_cleanliness": 0.6,
    "municipality_infrastructure": 1.15,
    "municipality_environment": 0.9,
}
P_FINE = {"illegal_parking": 0.7, "littering": 0.3, "illegal_dumping": 0.45, "noise": 0.5}
P_REJECT_GENUINE = 0.05  # "could not verify on site"
P_REJECT_ABUSIVE = 0.9
P_PAID = 0.8

DECISIONS_SQL = """
SELECT c.case_id, c.category, c.authority, c.routed_at, c.sla_due_at, r.fine_cents,
       bool_and(coalesce(l.is_abusive, false)) AS all_abusive
FROM ops.cases c
JOIN ops.reports rep USING (case_id)
LEFT JOIN eval.report_labels l ON l.event_id = rep.report_id
JOIN ref.category_rules r
  ON r.category = c.category AND tstzrange(r.valid_from, r.valid_to) @> c.first_reported_at
WHERE c.status = 'routed' AND c.routed_at <= %s
GROUP BY c.case_id, r.fine_cents
"""

PAYMENTS_SQL = """
SELECT f.fine_id, f.case_id, c.authority, f.amount_cents, f.issued_at
FROM ops.fines f JOIN ops.cases c USING (case_id)
WHERE f.paid_at IS NULL AND c.status = 'fined'
"""


def _rng(case_id: uuid.UUID, purpose: str) -> random.Random:
    return random.Random(f"{case_id}:{purpose}")


def _outcome(
    case_id: uuid.UUID, authority: str, outcome: str, at: datetime, **extra: Any
) -> dict[str, Any]:
    return {
        "schema": "authority.outcome/1",
        "event_id": str(uuid.uuid5(NAMESPACE, f"{case_id}:{outcome}")),
        "occurred_at": at.isoformat(),
        "case_id": str(case_id),
        "authority": authority,
        "outcome": outcome,
        **extra,
    }


def decide(row: tuple[Any, ...]) -> tuple[datetime, dict[str, Any]]:
    case_id, category, authority, routed_at, sla_due_at, fine_cents, all_abusive = row
    rng = _rng(case_id, "decision")
    sla = sla_due_at - routed_at
    delay = sla * SPEED[authority] * math.exp(rng.gauss(0, 0.6))
    at = routed_at + max(delay, timedelta(minutes=10))
    roll = rng.random()
    if roll < (P_REJECT_ABUSIVE if all_abusive else P_REJECT_GENUINE):
        return at, _outcome(case_id, authority, "rejected", at)
    if fine_cents and rng.random() < P_FINE.get(category, 0):
        fine_id = str(uuid.uuid5(NAMESPACE, f"{case_id}:fine"))
        extra = {"fine_id": fine_id, "amount_cents": fine_cents, "currency": "EUR"}
        return at, _outcome(case_id, authority, "fine_issued", at, **extra)
    return at, _outcome(case_id, authority, "resolved", at)


def simulate(conn: psycopg.Connection, producer: Producer, until: datetime) -> dict[str, int]:
    topic = get_settings().outcomes_topic
    counts: dict[str, int] = {}

    def emit(event: dict[str, Any]) -> None:
        producer.produce(topic, key=event["case_id"], value=json.dumps(event).encode())
        producer.poll(0)
        counts[event["outcome"]] = counts.get(event["outcome"], 0) + 1

    for row in conn.execute(DECISIONS_SQL, [until]).fetchall():
        at, event = decide(row)
        if at <= until:
            emit(event)

    for fine_id, case_id, authority, amount, issued_at in conn.execute(PAYMENTS_SQL).fetchall():
        rng = _rng(case_id, "payment")
        if rng.random() >= P_PAID:
            continue  # never paid; stays outstanding
        paid_at = issued_at + timedelta(days=rng.uniform(1, 25))
        if paid_at <= until:
            extra = {"fine_id": str(fine_id), "amount_cents": amount, "currency": "EUR"}
            emit(_outcome(case_id, authority, "fine_paid", paid_at, **extra))

    producer.flush(30)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit simulated authority outcomes.")
    parser.add_argument("--until", type=datetime.fromisoformat, default=datetime.now(UTC))
    args = parser.parse_args()
    ensure_topics()
    with connect() as conn:
        print(json.dumps(simulate(conn, make_producer(), args.until)))


if __name__ == "__main__":
    main()
