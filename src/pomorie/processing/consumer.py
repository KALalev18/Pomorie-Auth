"""The stream processor: consume both topics and apply each event in one DB transaction.

Delivery guarantee: Kafka offsets are committed only after the database transaction
commits. A crash between the two redelivers the event; the raw insert is keyed by
event_id, so the redelivered event is recognised and skipped. The effect is exactly-once
processing on top of at-least-once delivery.

    python -m pomorie.processing.consumer
"""

from __future__ import annotations

import json
import logging
import signal
import time
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from confluent_kafka import Consumer, KafkaError, Message, TopicPartition
from shapely.geometry import shape

from pomorie.config import get_settings
from pomorie.contracts import AUTHORITY_OUTCOME, REPORT_SUBMITTED, validate
from pomorie.db import connect
from pomorie.kafka import ensure_topics, make_consumer
from pomorie.processing.outcomes import InvalidOutcome, process_outcome
from pomorie.processing.reports import MissingRule, process_report
from pomorie.processing.validation import BoundaryCheck, Report, semantic_errors

log = logging.getLogger("pomorie.processor")

MAX_ATTEMPTS = 5  # then the event is parked in the dead-letter table so the stream moves on


@dataclass
class Rejected(Exception):
    stage: str
    reasons: list[str]
    event_id: str | None = None


def load_boundary(conn: psycopg.Connection) -> BoundaryCheck:
    row = conn.execute("SELECT ST_AsGeoJSON(geom) FROM ref.municipality_boundary").fetchone()
    if row is None:
        raise RuntimeError("reference data missing: run python -m pomorie.reference.load")
    return BoundaryCheck(shape(json.loads(row[0])))


def parse(value: bytes | None) -> dict[str, Any]:
    try:
        event = json.loads(value or b"")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Rejected("parse", [f"not valid JSON: {exc}"]) from exc
    if not isinstance(event, dict):
        raise Rejected("parse", ["event is not a JSON object"])
    return event


class Processor:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.boundary = load_boundary(conn)
        settings = get_settings()
        self.reports_topic = settings.reports_topic
        self.outcomes_topic = settings.outcomes_topic

    def handle(self, topic: str, partition: int, offset: int, value: bytes | None) -> str:
        """Apply one message. Returns what happened, for logs and tests."""
        try:
            with self.conn.transaction():
                return self._apply(topic, partition, offset, value)
        except Rejected as rejected:
            with self.conn.transaction():
                self.dead_letter(topic, partition, offset, value, rejected)
            return f"dead_letter:{rejected.stage}"

    def _apply(self, topic: str, partition: int, offset: int, value: bytes | None) -> str:
        event = parse(value)
        is_report = topic == self.reports_topic
        contract = REPORT_SUBMITTED if is_report else AUTHORITY_OUTCOME
        if errors := validate(contract, event):
            raise Rejected("contract", errors, _event_id(event))

        table = "raw.report_events" if is_report else "raw.outcome_events"
        landed = self.conn.execute(
            f"INSERT INTO {table} (event_id, payload, kafka_topic, kafka_partition, kafka_offset)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING RETURNING 1",
            [event["event_id"], json.dumps(event), topic, partition, offset],
        ).fetchone()
        if landed is None:
            return "duplicate_delivery"

        if is_report:
            report = Report.from_event(event)
            if errors := semantic_errors(report, self.boundary):
                raise Rejected("semantic", errors, report.event_id)
            try:
                result = process_report(self.conn, report)
            except MissingRule as exc:
                raise Rejected("semantic", [f"no_rule: {exc}"], report.event_id) from exc
            return "merged" if result.is_duplicate else "new_case"

        try:
            process_outcome(self.conn, event)
        except InvalidOutcome as exc:
            raise Rejected("semantic", [str(exc)], event["event_id"]) from exc
        return f"outcome:{event['outcome']}"

    def dead_letter(
        self, topic: str, partition: int, offset: int, value: bytes | None, rejected: Rejected
    ) -> None:
        self.conn.execute(
            "INSERT INTO raw.dead_letter (kafka_topic, kafka_partition, kafka_offset, payload,"
            " stage, reasons, event_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING",
            [
                topic,
                partition,
                offset,
                (value or b"").decode("utf-8", errors="replace"),
                rejected.stage,
                rejected.reasons,
                rejected.event_id,
            ],
        )


def _event_id(event: dict[str, Any]) -> str | None:
    try:
        return str(uuid.UUID(str(event.get("event_id"))))
    except ValueError:
        return None


def run(stop_after_idle_s: float | None = None) -> None:
    """Consume until stopped. ``stop_after_idle_s`` lets benchmarks exit when drained."""
    ensure_topics()
    settings = get_settings()
    consumer: Consumer = make_consumer(
        "pomorie-processor", [settings.reports_topic, settings.outcomes_topic]
    )
    running = True

    def stop(*_: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    with connect() as conn:
        processor = Processor(conn)
        idle_since = time.monotonic()
        while running:
            msg: Message | None = consumer.poll(1.0)
            if msg is None:
                if stop_after_idle_s and time.monotonic() - idle_since > stop_after_idle_s:
                    break
                continue
            idle_since = time.monotonic()
            if (error := msg.error()) is not None:
                if error.code() != KafkaError._PARTITION_EOF:
                    log.error("kafka error: %s", error)
                continue
            topic, partition, offset = msg.topic() or "", msg.partition() or 0, msg.offset() or 0
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    outcome = processor.handle(topic, partition, offset, msg.value())
                    break
                except psycopg.Error:
                    log.exception(
                        "attempt %d failed for %s[%d]@%d", attempt, topic, partition, offset
                    )
                    if conn.broken:
                        conn = connect()
                        processor = Processor(conn)
                    if attempt == MAX_ATTEMPTS:
                        with conn.transaction():
                            processor.dead_letter(
                                topic,
                                partition,
                                offset,
                                msg.value(),
                                Rejected("processing", ["processing failed after retries"]),
                            )
                        outcome = "dead_letter:processing"
                    else:
                        time.sleep(2**attempt)
            log.debug("%s[%d]@%d -> %s", topic, partition, offset, outcome)
            consumer.commit(
                offsets=[TopicPartition(topic, partition, offset + 1)], asynchronous=False
            )
    consumer.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()


if __name__ == "__main__":
    main()
