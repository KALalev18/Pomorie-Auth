CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- One schema per responsibility, so access can be granted per schema.
CREATE SCHEMA identity;  -- personal data (name, email); only the API and erasure job touch it
CREATE SCHEMA raw;       -- events exactly as received from Kafka, plus the dead-letter table
CREATE SCHEMA ref;       -- reference data: boundary, OSM features, routing rules
CREATE SCHEMA ops;       -- operational state written by the stream processor
CREATE SCHEMA ledger;    -- append-only, double-entry reward ledger
CREATE SCHEMA eval;      -- generator ground truth, never read by the pipeline itself
