select
    report_id,
    case_id,
    reporter_key,
    category,
    settlement,
    report_date as date_key,
    received_at,
    occurred_at,
    lat,
    lon,
    accuracy_m,
    street,
    nearest_landmark,
    dist_school_m,
    dist_beach_m,
    is_duplicate,
    is_flagged,
    fraud_flags,
    photo_count,
    has_plate,
    -- Pipeline latency: from the API accepting the report to the case being routed.
    extract(epoch from processed_at - received_at) * 1000 as processing_latency_ms
from {{ ref('stg_reports') }}
