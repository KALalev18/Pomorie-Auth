-- Settlement-level location dimension (reports carry the nearest OSM settlement).
select
    settlement,
    lat,
    lon
from {{ ref('stg_settlements') }}
union all
select
    'unknown' as settlement,
    null as lat,
    null as lon
