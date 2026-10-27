-- Landing tables keyed by event_id: replaying a topic never duplicates rows.
CREATE TABLE raw.report_events (
    event_id         uuid PRIMARY KEY,
    payload          jsonb NOT NULL,
    kafka_topic      text NOT NULL,
    kafka_partition  integer NOT NULL,
    kafka_offset     bigint NOT NULL,
    ingested_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.outcome_events (
    event_id         uuid PRIMARY KEY,
    payload          jsonb NOT NULL,
    kafka_topic      text NOT NULL,
    kafka_partition  integer NOT NULL,
    kafka_offset     bigint NOT NULL,
    ingested_at      timestamptz NOT NULL DEFAULT now()
);

-- Anything that fails the contract or the semantic checks, with the reasons.
CREATE TABLE raw.dead_letter (
    dead_letter_id   bigserial PRIMARY KEY,
    kafka_topic      text NOT NULL,
    kafka_partition  integer NOT NULL,
    kafka_offset     bigint NOT NULL,
    payload          text NOT NULL,
    stage            text NOT NULL CHECK (stage IN ('parse', 'contract', 'semantic')),
    reasons          text[] NOT NULL CHECK (cardinality(reasons) > 0),
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kafka_topic, kafka_partition, kafka_offset)
);
