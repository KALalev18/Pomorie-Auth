-- Enrich one report location with OpenStreetMap context.
-- Distances are geodesic metres. "geog" is a stored, GiST-indexed geography column, so
-- ST_DWithin and the KNN operator (<->) use the index instead of scanning every feature.
with p as (
    select st_setsrid(st_makepoint(%(lon)s, %(lat)s), 4326)::geography as g
)

select
    (
        select f.name from ref.osm_features as f
        where f.kind = 'settlement'
        order by f.geog <-> p.g limit 1
    ) as settlement,
    (
        select f.name from ref.osm_features as f
        where f.kind = 'street' and st_dwithin(f.geog, p.g, 75)
        order by st_distance(f.geog, p.g) limit 1
    ) as street,
    (
        select f.name from ref.osm_features as f
        where f.kind = 'landmark' and st_dwithin(f.geog, p.g, 500)
        order by st_distance(f.geog, p.g) limit 1
    ) as nearest_landmark,
    (
        select round(st_distance(f.geog, p.g))::int from ref.osm_features as f
        where f.kind = 'school'
        order by f.geog <-> p.g limit 1
    ) as dist_school_m,
    (
        select round(st_distance(f.geog, p.g))::int from ref.osm_features as f
        where f.kind = 'beach'
        order by f.geog <-> p.g limit 1
    ) as dist_beach_m
from p
