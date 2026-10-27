-- Keep the exact bytes of rejected messages (they may not be valid text, e.g. NUL bytes),
-- so a fixed consumer can replay them unchanged.
ALTER TABLE raw.dead_letter
    ALTER COLUMN payload TYPE bytea USING convert_to(payload, 'UTF8');
