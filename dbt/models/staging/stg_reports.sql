-- One row per accepted report. reporter_id is replaced by an HMAC pseudonym here, the
-- only place the warehouse touches it, so no downstream model can join back to identity.
select
    report_id,
    case_id,
    {{ pseudonym('reporter_id', 'reporter') }} as reporter_key,
    category,
    st_y(geom::geometry) as lat,
    st_x(geom::geometry) as lon,
    accuracy_m,
    occurred_at,
    received_at,
    processed_at,
    received_at::date as report_date,
    coalesce(settlement, 'unknown') as settlement,
    street,
    nearest_landmark,
    dist_school_m,
    dist_beach_m,
    is_duplicate,
    fraud_flags,
    cardinality(fraud_flags) > 0 as is_flagged,
    cardinality(photo_keys) as photo_count,
    plate_hash is not null as has_plate
from {{ source('ops', 'reports') }}
