"""API -> Redpanda -> stream processor -> Postgres -> API, against the real services.

Uses its own Kafka topics and the throwaway test database, so it never touches demo data.
"""

import io
import json
import time
import uuid
from collections.abc import Iterator

import pytest
from confluent_kafka import KafkaException
from fastapi.testclient import TestClient
from PIL import Image

from pomorie import config, photos
from pomorie.db import connect
from pomorie.kafka import ensure_topics, make_consumer
from pomorie.processing.consumer import Runner

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_settings(db_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setenv("POSTGRES_DB", db_dsn.rsplit("/", 1)[1])
    monkeypatch.setenv("REPORTS_TOPIC", f"test.reports.{suffix}")
    monkeypatch.setenv("OUTCOMES_TOPIC", f"test.outcomes.{suffix}")
    config.get_settings.cache_clear()
    photos.s3_client.cache_clear()
    try:
        ensure_topics()
    except KafkaException:
        pytest.skip("Redpanda not available (run: docker compose up -d redpanda)")
    yield
    config.get_settings.cache_clear()


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(out, format="JPEG")
    return out.getvalue()


def test_report_flows_from_api_to_routed_case(isolated_settings: None) -> None:
    from pomorie.api.app import app

    with TestClient(app) as client:
        reporter = client.post(
            "/reporters", json={"display_name": "E2E", "email": "e2e@example.org"}
        ).json()["reporter_id"]
        report = {
            "reporter_id": reporter,
            "category": "illegal_parking",
            "lat": 42.5684,
            "lon": 27.6168,
            "plate": "А 1234 ВК",
        }
        idempotency_key = str(uuid.uuid4())
        accepted = client.post(
            "/reports",
            data={"report": json.dumps(report)},
            files={"photos": ("p.jpg", _jpeg(), "image/jpeg")},
            headers={"Idempotency-Key": idempotency_key},
        )
        assert accepted.status_code == 202
        event_id = accepted.json()["event_id"]
        assert event_id == idempotency_key
        assert client.get(f"/reports/{event_id}").json()["status"] == "processing"

        settings = config.get_settings()
        consumer = make_consumer(f"e2e-{uuid.uuid4().hex[:6]}", [settings.reports_topic])
        try:
            with connect(autocommit=True) as conn:
                runner = Runner(conn)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    batch = [m for m in consumer.consume(10, timeout=1.0) if m.error() is None]
                    if batch:
                        runner.process_batch(batch)
                        break
        finally:
            consumer.close()

        status = client.get(f"/reports/{event_id}").json()
        assert status["status"] == "routed"
        assert status["authority"] == "traffic_police"
