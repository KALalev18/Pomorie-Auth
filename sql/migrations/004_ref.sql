CREATE TABLE ref.municipality_boundary (
    boundary_id  integer PRIMARY KEY DEFAULT 1 CHECK (boundary_id = 1),
    name         text NOT NULL,
    geom         geometry(MultiPolygon, 4326) NOT NULL
);

-- OpenStreetMap features used for enrichment (© OpenStreetMap contributors, ODbL).
CREATE TABLE ref.osm_features (
    osm_type  text NOT NULL CHECK (osm_type IN ('node', 'way', 'relation')),
    osm_id    bigint NOT NULL,
    kind      text NOT NULL CHECK (kind IN ('settlement', 'street', 'school', 'beach', 'landmark')),
    name      text,
    geom      geometry(Geometry, 4326) NOT NULL,
    PRIMARY KEY (osm_type, osm_id, kind)
);
CREATE INDEX osm_features_geog_idx ON ref.osm_features USING gist ((geom::geography));
CREATE INDEX osm_features_kind_idx ON ref.osm_features (kind);

-- Routing and reward rules, versioned in place (type-2): a rule change closes the old row
-- and opens a new one, so a case is always judged by the rule valid when it was reported.
CREATE TABLE ref.category_rules (
    category            text NOT NULL,
    authority           text NOT NULL,
    sla_hours           integer NOT NULL CHECK (sla_hours > 0),
    dedup_radius_m      integer NOT NULL CHECK (dedup_radius_m > 0),
    dedup_window_hours  integer NOT NULL CHECK (dedup_window_hours > 0),
    fine_cents          integer CHECK (fine_cents > 0),
    reward_share_bp     integer NOT NULL DEFAULT 0 CHECK (reward_share_bp BETWEEN 0 AND 5000),
    valid_from          timestamptz NOT NULL,
    valid_to            timestamptz,
    PRIMARY KEY (category, valid_from),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    -- No two versions of the same category's rule may overlap in time.
    EXCLUDE USING gist (
        category WITH =,
        tstzrange(valid_from, valid_to) WITH &&
    )
);
