-- Enrich one report location with OpenStreetMap context.
-- Distances are geodesic metres (geography). The feature table is small (~600 rows), so
-- exact ST_Distance ordering is cheap; at city scale a KNN index scan would replace it.
with p as (
    select st_setsrid(st_makepoint(%(lon)s, %(lat)s), 4326)::geography as g
)

select
    (
        select f.name from ref.osm_features as f
        where f.kind = 'settlement'
        order by st_distance(f.geom::geography, p.g) limit 1
    ) as settlement,
    (
        select f.name from ref.osm_features as f
        where f.kind = 'street' and st_dwithin(f.geom::geography, p.g, 75)
        order by st_distance(f.geom::geography, p.g) limit 1
    ) as street,
    (
        select f.name from ref.osm_features as f
        where f.kind = 'landmark' and st_dwithin(f.geom::geography, p.g, 500)
        order by st_distance(f.geom::geography, p.g) limit 1
    ) as nearest_landmark,
    (
        select round(min(st_distance(f.geom::geography, p.g)))::int
        from ref.osm_features as f where f.kind = 'school'
    ) as dist_school_m,
    (
        select round(min(st_distance(f.geom::geography, p.g)))::int
        from ref.osm_features as f where f.kind = 'beach'
    ) as dist_beach_m
from p
