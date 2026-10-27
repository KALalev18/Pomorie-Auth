-- Reporter identity is stored apart from report data. Events and analytics only carry
-- reporter_id (a random UUID); the warehouse goes one step further and uses an HMAC of it.
CREATE TABLE identity.reporters (
    reporter_id   uuid PRIMARY KEY,
    display_name  text,
    email         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    erased_at     timestamptz,
    CHECK (erased_at IS NULL OR (display_name IS NULL AND email IS NULL))
);

CREATE TABLE identity.erasure_requests (
    request_id    bigserial PRIMARY KEY,
    reporter_id   uuid NOT NULL,
    requested_at  timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz,
    -- What the erasure job did, for the audit trail (counts, not content).
    summary       jsonb
);
