-- Lets the API tell a reporter why their report was rejected. Nullable: events that fail
-- to parse have no readable event_id.
ALTER TABLE raw.dead_letter ADD COLUMN event_id uuid;
CREATE INDEX dead_letter_event_idx ON raw.dead_letter (event_id) WHERE event_id IS NOT NULL;
