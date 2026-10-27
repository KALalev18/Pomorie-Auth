"""Kafka (Redpanda) clients and topic setup."""

from __future__ import annotations

import json
from typing import Any

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

from pomorie.config import get_settings

# Reports are keyed by category, so all reports of one category land on one partition and
# are processed in order by one consumer. Deduplication compares a report with open cases
# of the same category, so this ordering removes races without any locking.
REPORT_PARTITIONS = 4
OUTCOME_PARTITIONS = 2


def ensure_topics() -> None:
    """Create the topics, or fail if one exists with the wrong partition count.

    Auto-creation is disabled on the broker: an auto-created topic gets one partition,
    which silently removes all parallelism (this happened once in development).
    """
    settings = get_settings()
    admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})
    wanted = {
        settings.reports_topic: REPORT_PARTITIONS,
        settings.outcomes_topic: OUTCOME_PARTITIONS,
    }
    existing = admin.list_topics(timeout=10).topics
    for topic, partitions in wanted.items():
        if topic in existing and len(existing[topic].partitions) != partitions:
            raise RuntimeError(
                f"topic {topic} has {len(existing[topic].partitions)} partitions, "
                f"expected {partitions}"
            )
    new = [
        NewTopic(t, num_partitions=n, replication_factor=1)
        for t, n in wanted.items()
        if t not in existing
    ]
    for future in admin.create_topics(new).values() if new else []:
        try:
            future.result()
        except KafkaException as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


def make_producer() -> Producer:
    return Producer(
        {
            "bootstrap.servers": get_settings().kafka_bootstrap,
            "enable.idempotence": True,  # no duplicates from producer retries
            "acks": "all",
            "linger.ms": 5,
        }
    )


def make_consumer(group_id: str, topics: list[str]) -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": get_settings().kafka_bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            # Offsets are committed only after the database transaction commits:
            # at-least-once delivery, made effectively-once by idempotent writes.
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe(topics)
    return consumer


def publish(producer: Producer, topic: str, key: str, event: dict[str, Any]) -> None:
    errors: list[str] = []

    def on_delivery(err: Any, _msg: Any) -> None:
        if err is not None:
            errors.append(str(err))

    producer.produce(topic, key=key, value=json.dumps(event).encode(), on_delivery=on_delivery)
    producer.flush(10)
    if errors:
        raise KafkaException(errors[0])


if __name__ == "__main__":
    ensure_topics()
    print("topics ready")
