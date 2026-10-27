-- The warehouse (dbt) computes HMAC pseudonyms in SQL with the same key and format as
-- pomorie.privacy.pseudonym, so analytics never sees a raw reporter_id.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
