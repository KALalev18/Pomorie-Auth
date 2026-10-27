import json
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from pomorie.processing.consumer import Processor
from pomorie.reconciliation import reconcile_day

pytestmark = pytest.mark.integration

T0 = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
PAID = T0 + timedelta(days=3)


def _paid_parking_fine(conn: psycopg.Connection) -> str:
    processor = Processor(conn)
    event_id = str(uuid.uuid4())
    report = {
        "schema": "report.submitted/1",
        "event_id": event_id,
        "occurred_at": T0.isoformat(),
        "received_at": T0.isoformat(),
        "reporter_id": str(uuid.uuid4()),
        "category": "illegal_parking",
        "location": {"lat": 42.5684, "lon": 27.6168},
    }
    processor.handle("reports.submitted.v1", 0, 0, json.dumps(report).encode())
    (case_id,) = conn.execute(
        "SELECT case_id FROM ops.reports WHERE report_id = %s", [event_id]
    ).fetchone() or ("",)
    fine_id = str(uuid.uuid4())
    fine = {"fine_id": fine_id, "amount_cents": 7500, "currency": "EUR"}
    for outcome, at in [("fine_issued", T0 + timedelta(hours=2)), ("fine_paid", PAID)]:
        event = {
            "schema": "authority.outcome/1",
            "event_id": str(uuid.uuid4()),
            "occurred_at": at.isoformat(),
            "case_id": str(case_id),
            "authority": "traffic_police",
            "outcome": outcome,
            **fine,
        }
        processor.handle("authority.outcomes.v1", 0, 0, json.dumps(event).encode())
    return fine_id


def test_consistent_ledger_reconciles(conn: psycopg.Connection) -> None:
    _paid_parking_fine(conn)
    result = reconcile_day(conn, PAID.date())
    assert result["passed"], result["problems"]
    assert result["accrued_cents"] == result["expected_cents"] == 1125


def test_tampered_fine_is_detected(conn: psycopg.Connection) -> None:
    fine_id = _paid_parking_fine(conn)
    # Someone changes the fine after the reward was paid out: the books no longer match.
    conn.execute("UPDATE ops.fines SET amount_cents = 10000 WHERE fine_id = %s", [fine_id])
    result = reconcile_day(conn, PAID.date())
    assert not result["passed"]
    assert "fines imply 1500 cents" in result["problems"][0]
    (recorded,) = conn.execute(
        "SELECT count(*) FROM ledger.reconciliation_runs WHERE NOT passed"
    ).fetchone() or (0,)
    assert recorded == 1
