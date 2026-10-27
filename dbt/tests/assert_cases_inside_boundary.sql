-- Every case centroid lies inside the municipality, or within the processor's coastal
-- tolerance of it. The cheap planar ST_Covers (PostGIS caches the prepared polygon across
-- rows) settles almost every case; only the few near the coast need the geodesic check.
with points as (
    select
        case_id,
        st_setsrid(st_makepoint(lon, lat), 4326) as geom
    from {{ ref('fct_cases') }}
)

select p.case_id
from points as p
cross join {{ source('ref', 'municipality_boundary') }} as b
where
    not st_covers(b.geom, p.geom)
    and not st_dwithin(b.geom::geography, p.geom::geography, {{ var('boundary_tolerance_m') }})
