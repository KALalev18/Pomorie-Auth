select
    osm_id,
    name as settlement,
    st_y(geom) as lat,
    st_x(geom) as lon
from {{ source('ref', 'osm_features') }}
where kind = 'settlement'
