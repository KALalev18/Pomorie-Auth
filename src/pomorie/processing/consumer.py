"""The stream processor: consume both topics and apply each event in one DB transaction.

Delivery guarantee: Kafka offsets are committed only after the database transaction
commits. A crash between the two redelivers the event; the raw insert is keyed by
event_id, so the redelivered event is recognised and skipped. The effect is exactly-once
processing on top of at-least-once delivery.

    python -m pomorie.processing.consumer
"""

from __future__ import annotations

import argparse
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
from pomorie.processing.reports import MissingRule, RuleBook, process_report
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
        self.rules = RuleBook(conn)
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
                rule = self.rules.at(report.category, report.received_at)
            except MissingRule as exc:
                raise Rejected("semantic", [f"no_rule: {exc}"], report.event_id) from exc
            result = process_report(self.conn, report, rule)
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
                value or b"",
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


def _commit_offsets(consumer: Consumer, messages: list[Message]) -> None:
    """Commit the next offset per partition, after the database has committed."""
    latest: dict[tuple[str, int], int] = {}
    for msg in messages:
        latest[(msg.topic() or "", msg.partition() or 0)] = (msg.offset() or 0) + 1
    consumer.commit(
        offsets=[TopicPartition(t, p, o) for (t, p), o in latest.items()], asynchronous=False
    )


class Runner:
    """Micro-batching: one database transaction per batch, one savepoint per message.

    A commit costs an fsync (about 3 ms on Docker Desktop), so committing once per batch
    instead of once per event is the biggest single saving. Each message still gets its
    own savepoint, so a rejected event goes to the dead-letter table without affecting the
    rest of the batch. If the batch itself fails (database error), it is rolled back and
    replayed one message at a time with retries, which isolates a poison message.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.processor = Processor(conn)

    def _reconnect(self) -> None:
        if self.conn.broken:
            self.conn = connect(autocommit=True)
            self.processor = Processor(self.conn)

    def _handle(self, msg: Message) -> str:
        return self.processor.handle(
            msg.topic() or "", msg.partition() or 0, msg.offset() or 0, msg.value()
        )

    def process_batch(self, batch: list[Message]) -> None:
        try:
            with self.conn.transaction():
                for msg in batch:
                    self._handle(msg)
            return
        except psycopg.Error:
            log.exception("batch of %d failed; replaying one message at a time", len(batch))
            self._reconnect()
        for msg in batch:
            self.process_one(msg)

    def process_one(self, msg: Message) -> None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with self.conn.transaction():
                    self._handle(msg)
                return
            except psycopg.Error:
                log.exception("attempt %d failed for offset %s", attempt, msg.offset())
                self._reconnect()
                time.sleep(min(2**attempt, 30))
        with self.conn.transaction():
            self.processor.dead_letter(
                msg.topic() or "",
                msg.partition() or 0,
                msg.offset() or 0,
                msg.value(),
                Rejected("processing", ["processing failed after retries"]),
            )


def run(stop_after_idle_s: float | None = None, batch_size: int = 500) -> None:
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

    # Autocommit connection: transactions are opened explicitly per batch.
    with connect(autocommit=True) as conn:
        runner = Runner(conn)
        idle_since = time.monotonic()
        while running:
            messages = consumer.consume(num_messages=batch_size, timeout=1.0)
            batch = []
            for msg in messages:
                error = msg.error()
                if error is None:
                    batch.append(msg)
                elif error.code() != KafkaError._PARTITION_EOF:
                    log.error("kafka error: %s", error)
            if not batch:
                # Only count idle time once partitions are assigned: joining the group
                # after a restart can take longer than the idle limit.
                if not consumer.assignment():
                    idle_since = time.monotonic()
                elif stop_after_idle_s and time.monotonic() - idle_since > stop_after_idle_s:
                    break
                continue
            idle_since = time.monotonic()
            runner.process_batch(batch)
            _commit_offsets(consumer, batch)
    consumer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the stream processor.")
    parser.add_argument("--drain", action="store_true", help="exit after 10 s without messages")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run(stop_after_idle_s=10 if args.drain else None)


if __name__ == "__main__":
    main()
