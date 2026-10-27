import json
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from pomorie.gdpr import apply_retention, process_erasure_requests
from pomorie.processing.consumer import Processor

pytestmark = pytest.mark.integration

T0 = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, keys: list[str]) -> int:
        self.deleted += keys
        return len(keys)


def _submit(processor: Processor, reporter: uuid.UUID, description: str, at: datetime) -> str:
    event_id = str(uuid.uuid4())
    event = {
        "schema": "report.submitted/1",
        "event_id": event_id,
        "occurred_at": at.isoformat(),
        "received_at": at.isoformat(),
        "reporter_id": str(reporter),
        "category": "littering",
        "location": {"lat": 42.5684, "lon": 27.6168},
        "description": description,
        "photo_keys": [f"photos/{event_id}/{'b' * 32}.jpg"],
    }
    processor.handle("reports.submitted.v1", 0, 0, json.dumps(event).encode())
    return event_id


def test_erasure_propagates_through_the_pipeline(conn: psycopg.Connection) -> None:
    reporter = uuid.uuid4()
    conn.execute(
        "INSERT INTO identity.reporters VALUES (%s, 'Test Person', 't@example.org')", [reporter]
    )
    processor = Processor(conn)
    event_id = _submit(processor, reporter, "Bags of rubbish by my house at No. 12", T0)
    # A rejected event from the same reporter, holding its raw payload.
    processor.handle("reports.submitted.v1", 0, 999, f'{{"reporter_id": "{reporter}"'.encode())
    conn.execute("INSERT INTO identity.erasure_requests (reporter_id) VALUES (%s)", [reporter])

    storage = FakeStorage()
    assert process_erasure_requests(conn, storage.delete) == 1

    assert storage.deleted == [f"photos/{event_id}/{'b' * 32}.jpg"]
    assert conn.execute(
        "SELECT display_name, email, erased_at IS NOT NULL FROM identity.reporters"
        " WHERE reporter_id = %s",
        [reporter],
    ).fetchone() == (None, None, True)
    assert conn.execute(
        "SELECT description, photo_keys FROM ops.reports WHERE report_id = %s", [event_id]
    ).fetchone() == (None, [])
    (payload,) = conn.execute(
        "SELECT payload FROM raw.report_events WHERE event_id = %s", [event_id]
    ).fetchone() or ({},)
    assert "description" not in payload and "photo_keys" not in payload
    assert payload["category"] == "littering"  # the case itself remains usable
    assert conn.execute(
        "SELECT count(*) FROM raw.dead_letter WHERE position(%s::bytea IN payload) > 0",
        [str(reporter).encode()],
    ).fetchone() == (0,)
    (summary,) = conn.execute(
        "SELECT summary FROM identity.erasure_requests WHERE reporter_id = %s", [reporter]
    ).fetchone() or ({},)
    assert summary["photos"] == 1 and summary["dead_letters"] == 1
    assert process_erasure_requests(conn, storage.delete) == 0  # nothing left to do


def test_retention_removes_expired_personal_data(conn: psycopg.Connection) -> None:
    processor = Processor(conn)
    old = _submit(processor, uuid.uuid4(), "old", T0)
    recent = _submit(processor, uuid.uuid4(), "recent", T0 + timedelta(days=300))
    conn.execute(
        "UPDATE ops.cases SET status = 'resolved', closed_at = %s"
        " WHERE case_id = (SELECT case_id FROM ops.reports WHERE report_id = %s)",
        [T0 + timedelta(days=1), old],
    )

    storage = FakeStorage()
    result = apply_retention(conn, now=T0 + timedelta(days=400), delete_photos=storage.delete)

    assert result["photos"] == 1 and result["descriptions"] == 1
    assert conn.execute(
        "SELECT description FROM ops.reports WHERE report_id = %s", [old]
    ).fetchone() == (None,)
    assert conn.execute(
        "SELECT description FROM ops.reports WHERE report_id = %s", [recent]
    ).fetchone() == ("recent",)
