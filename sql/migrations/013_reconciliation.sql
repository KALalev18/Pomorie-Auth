-- Audit trail of daily ledger reconciliations (one row per run).
CREATE TABLE ledger.reconciliation_runs (
    run_id          bigserial PRIMARY KEY,
    day             date NOT NULL,
    checked_at      timestamptz NOT NULL DEFAULT now(),
    expected_cents  bigint NOT NULL,
    accrued_cents   bigint NOT NULL,
    passed          boolean NOT NULL,
    problems        text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX reconciliation_runs_day_idx ON ledger.reconciliation_runs (day);
