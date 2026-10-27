-- Lookups made by the stream processor for every report.
CREATE INDEX reports_plate_idx ON ops.reports (reporter_id, plate_hash, received_at)
    WHERE plate_hash IS NOT NULL;
CREATE INDEX cases_dedup_lookup_idx ON ops.cases (category, status, last_reported_at);
CREATE INDEX fines_unpaid_idx ON ops.fines (case_id) WHERE paid_at IS NULL;

-- Events that keep failing for an unexpected reason are parked so the stream keeps moving.
ALTER TABLE raw.dead_letter DROP CONSTRAINT dead_letter_stage_check;
ALTER TABLE raw.dead_letter ADD CONSTRAINT dead_letter_stage_check
    CHECK (stage IN ('parse', 'contract', 'semantic', 'processing'));
