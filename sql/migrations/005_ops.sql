-- A case is one real-world issue; several reports can be merged into it by deduplication.
CREATE TABLE ops.cases (
    case_id            uuid PRIMARY KEY,
    category           text NOT NULL,
    authority          text NOT NULL,
    status             text NOT NULL CHECK (status IN ('routed', 'rejected', 'resolved', 'fined', 'paid')),
    centroid           geography(Point, 4326) NOT NULL,
    report_count       integer NOT NULL DEFAULT 1 CHECK (report_count > 0),
    first_reported_at  timestamptz NOT NULL,
    last_reported_at   timestamptz NOT NULL,
    routed_at          timestamptz NOT NULL,
    sla_due_at         timestamptz NOT NULL,
    closed_at          timestamptz,
    -- Fraud checks put a case on hold; no reward is paid until a reviewer approves it.
    needs_review       boolean NOT NULL DEFAULT false,
    review_reasons     text[] NOT NULL DEFAULT '{}',
    review_decision    text CHECK (review_decision IN ('approved', 'rejected')),
    reviewed_at        timestamptz,
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cases_open_lookup_idx ON ops.cases USING gist (centroid) WHERE status = 'routed';
CREATE INDEX cases_category_last_idx ON ops.cases (category, last_reported_at);

CREATE TABLE ops.reports (
    report_id         uuid PRIMARY KEY,  -- = event_id of report.submitted
    case_id           uuid NOT NULL REFERENCES ops.cases,
    reporter_id       uuid NOT NULL,
    category          text NOT NULL,
    geom              geography(Point, 4326) NOT NULL,
    accuracy_m        numeric,
    occurred_at       timestamptz NOT NULL,
    received_at       timestamptz NOT NULL,
    description       text,
    photo_keys        text[] NOT NULL DEFAULT '{}',
    plate_hash        text,
    settlement        text,
    street            text,
    nearest_landmark  text,
    dist_school_m     integer,
    dist_beach_m      integer,
    is_duplicate      boolean NOT NULL,
    fraud_flags       text[] NOT NULL DEFAULT '{}',
    processed_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX reports_case_idx ON ops.reports (case_id);
CREATE INDEX reports_reporter_idx ON ops.reports (reporter_id, received_at);

CREATE TABLE ops.case_status_history (
    case_id     uuid NOT NULL REFERENCES ops.cases,
    status      text NOT NULL,
    changed_at  timestamptz NOT NULL,
    source      text NOT NULL,
    PRIMARY KEY (case_id, status, changed_at)
);

CREATE TABLE ops.fines (
    fine_id       uuid PRIMARY KEY,
    case_id       uuid NOT NULL REFERENCES ops.cases,
    authority     text NOT NULL,
    amount_cents  integer NOT NULL CHECK (amount_cents > 0),
    currency      text NOT NULL DEFAULT 'EUR',
    issued_at     timestamptz NOT NULL,
    paid_at       timestamptz,
    CHECK (paid_at IS NULL OR paid_at >= issued_at)
);
