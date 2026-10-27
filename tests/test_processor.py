"""The stream processor against a real PostGIS database (no Kafka needed: messages are
handed to ``Processor.handle`` with made-up topic/partition/offset)."""

import itertools
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from pomorie.processing.consumer import Processor
from pomorie.processing.ledger import accrue_pending_rewards

pytestmark = pytest.mark.integration

REPORTS, OUTCOMES = "reports.submitted.v1", "authority.outcomes.v1"
T0 = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
POMORIE = (42.5684, 27.6168)  # town centre
_offsets = itertools.count()


@pytest.fixture
def processor(conn: psycopg.Connection) -> Processor:
    return Processor(conn)


def report_event(
    category: str = "illegal_parking",
    at: datetime = T0,
    lat: float = POMORIE[0],
    lon: float = POMORIE[1],
    reporter: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "schema": "report.submitted/1",
        "event_id": str(uuid.uuid4()),
        "occurred_at": at.isoformat(),
        "received_at": at.isoformat(),
        "reporter_id": reporter or str(uuid.uuid4()),
        "category": category,
        "location": {"lat": lat, "lon": lon, "accuracy_m": 8},
        **extra,
    }


def outcome_event(case_id: str, outcome: str, at: datetime, **extra: Any) -> dict[str, Any]:
    return {
        "schema": "authority.outcome/1",
        "event_id": str(uuid.uuid4()),
        "occurred_at": at.isoformat(),
        "case_id": case_id,
        "authority": "traffic_police",
        "outcome": outcome,
        **extra,
    }


def send(processor: Processor, topic: str, event: dict[str, Any] | bytes) -> str:
    value = event if isinstance(event, bytes) else json.dumps(event).encode()
    return processor.handle(topic, 0, next(_offsets), value)


def case_of(conn: psycopg.Connection, event: dict[str, Any]) -> str:
    row = conn.execute(
        "SELECT case_id FROM ops.reports WHERE report_id = %s", [event["event_id"]]
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_report_creates_routed_enriched_case(
    conn: psycopg.Connection, processor: Processor
) -> None:
    event = report_event()
    assert send(processor, REPORTS, event) == "new_case"
    authority, sla_due, settlement = conn.execute(
        "SELECT c.authority, c.sla_due_at, r.settlement FROM ops.cases c"
        " JOIN ops.reports r USING (case_id) WHERE r.report_id = %s",
        [event["event_id"]],
    ).fetchone() or (None, None, None)
    assert authority == "traffic_police"
    assert sla_due == T0 + timedelta(hours=4)
    assert settlement == "Поморие"


def test_nearby_report_in_window_merges(conn: psycopg.Connection, processor: Processor) -> None:
    first = report_event()
    second = report_event(at=T0 + timedelta(hours=1), lat=POMORIE[0] + 0.0001)  # ~11 m north
    other_category = report_event(category="littering", at=T0 + timedelta(hours=1))
    later = report_event(at=T0 + timedelta(hours=5))  # outside the 3 h parking window

    assert send(processor, REPORTS, first) == "new_case"
    assert send(processor, REPORTS, second) == "merged"
    assert send(processor, REPORTS, other_category) == "new_case"
    assert send(processor, REPORTS, later) == "new_case"
    assert case_of(conn, first) == case_of(conn, second) != case_of(conn, later)


def test_redelivered_event_is_applied_once(conn: psycopg.Connection, processor: Processor) -> None:
    event = report_event()
    assert send(processor, REPORTS, event) == "new_case"
    assert send(processor, REPORTS, event) == "duplicate_delivery"
    (count,) = conn.execute(
        "SELECT report_count FROM ops.cases WHERE case_id = %s", [case_of(conn, event)]
    ).fetchone() or (0,)
    assert count == 1


@pytest.mark.parametrize(
    ("payload", "stage"),
    [
        (b"{not json", "parse"),
        ({"schema": "report.submitted/1", "category": "illegal_parking"}, "contract"),
        (report_event(lat=42.70, lon=27.80), "semantic"),  # in the Black Sea
    ],
)
def test_bad_events_go_to_dead_letter(
    conn: psycopg.Connection, processor: Processor, payload: dict[str, Any] | bytes, stage: str
) -> None:
    assert send(processor, REPORTS, payload) == f"dead_letter:{stage}"
    (reasons,) = conn.execute(
        "SELECT reasons FROM raw.dead_letter ORDER BY dead_letter_id DESC LIMIT 1"
    ).fetchone() or ([],)
    assert reasons


def test_fine_paid_accrues_balanced_reward(conn: psycopg.Connection, processor: Processor) -> None:
    reporter = str(uuid.uuid4())
    event = report_event(reporter=reporter)
    send(processor, REPORTS, event)
    case_id, fine_id = case_of(conn, event), str(uuid.uuid4())
    fine = {"fine_id": fine_id, "amount_cents": 7500, "currency": "EUR"}

    assert (
        send(
            processor,
            OUTCOMES,
            outcome_event(case_id, "fine_issued", T0 + timedelta(hours=2), **fine),
        )
        == "outcome:fine_issued"
    )
    assert (
        send(
            processor, OUTCOMES, outcome_event(case_id, "fine_paid", T0 + timedelta(days=5), **fine)
        )
        == "outcome:fine_paid"
    )

    # July rule: 15 % of a 75 EUR fine.
    rows = conn.execute(
        "SELECT e.account_id, e.amount_cents FROM ledger.entries e"
        " JOIN ledger.transactions t USING (txn_id) WHERE t.fine_id = %s ORDER BY e.amount_cents",
        [fine_id],
    ).fetchall()
    assert rows == [(f"payable:{reporter}", -1125), ("reward_expense", 1125)]
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")  # the deferred balance check passes


def test_rule_version_is_chosen_by_report_time(
    conn: psycopg.Connection, processor: Processor
) -> None:
    june = T0 - timedelta(days=30)  # parking reward share was 20 % before 1 July
    event = report_event(at=june)
    send(processor, REPORTS, event)
    case_id, fine_id = case_of(conn, event), str(uuid.uuid4())
    fine = {"fine_id": fine_id, "amount_cents": 5000, "currency": "EUR"}
    send(
        processor,
        OUTCOMES,
        outcome_event(case_id, "fine_issued", june + timedelta(hours=1), **fine),
    )
    send(processor, OUTCOMES, outcome_event(case_id, "fine_paid", T0, **fine))  # paid in July
    (amount,) = conn.execute(
        "SELECT e.amount_cents FROM ledger.entries e JOIN ledger.transactions t USING (txn_id)"
        " WHERE t.fine_id = %s AND e.account_id = 'reward_expense'",
        [fine_id],
    ).fetchone() or (0,)
    assert amount == 1000


def test_flagged_case_waits_for_review(conn: psycopg.Connection, processor: Processor) -> None:
    reporter = str(uuid.uuid4())
    # Six reports in a few minutes from one reporter: the sixth is flagged as a burst.
    events = [
        report_event(reporter=reporter, at=T0 + timedelta(minutes=i), lat=42.5684 + i * 0.003)
        for i in range(6)
    ]
    for event in events:
        send(processor, REPORTS, event)
    flagged = case_of(conn, events[-1])
    (needs_review, reasons) = conn.execute(
        "SELECT needs_review, review_reasons FROM ops.cases WHERE case_id = %s", [flagged]
    ).fetchone() or (False, [])
    assert needs_review and reasons == ["burst"]

    fine = {"fine_id": str(uuid.uuid4()), "amount_cents": 7500, "currency": "EUR"}
    send(
        processor, OUTCOMES, outcome_event(flagged, "fine_issued", T0 + timedelta(hours=1), **fine)
    )
    send(processor, OUTCOMES, outcome_event(flagged, "fine_paid", T0 + timedelta(days=2), **fine))
    assert accrue_pending_rewards(conn) == 0  # on hold

    conn.execute("UPDATE ops.cases SET review_decision = 'approved' WHERE case_id = %s", [flagged])
    assert accrue_pending_rewards(conn) == 1
    assert accrue_pending_rewards(conn) == 0  # idempotent


def test_invalid_transition_is_dead_lettered(
    conn: psycopg.Connection, processor: Processor
) -> None:
    event = report_event()
    send(processor, REPORTS, event)
    paid_before_issued = outcome_event(
        case_of(conn, event),
        "fine_paid",
        T0 + timedelta(hours=1),
        fine_id=str(uuid.uuid4()),
        amount_cents=100,
        currency="EUR",
    )
    assert send(processor, OUTCOMES, paid_before_issued) == "dead_letter:semantic"
