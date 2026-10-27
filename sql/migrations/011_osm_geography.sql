-- Enrichment measures geodesic distance for every report. Store the geography once instead
-- of casting ~600 geometries per query, and index it for ST_DWithin and KNN (<->).
DROP INDEX ref.osm_features_geog_idx;
ALTER TABLE ref.osm_features
    ADD COLUMN geog geography GENERATED ALWAYS AS (geom::geography) STORED;
CREATE INDEX osm_features_geog_idx ON ref.osm_features USING gist (geog);
