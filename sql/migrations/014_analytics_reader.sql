-- Least privilege for the dashboard: it may read the analytics marts and nothing else
-- (no identity, ops, raw or ledger tables). dbt creates the mart tables as the owner role,
-- so default privileges grant SELECT on every table it (re)creates.
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE ROLE analytics_reader NOLOGIN;
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO analytics_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO analytics_reader;
