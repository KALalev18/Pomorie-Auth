select
    case_id,
    category,
    authority,
    status,
    st_y(centroid::geometry) as lat,
    st_x(centroid::geometry) as lon,
    report_count,
    first_reported_at,
    last_reported_at,
    routed_at,
    sla_due_at,
    closed_at,
    needs_review,
    review_reasons,
    review_decision,
    reviewed_at
from {{ source('ops', 'cases') }}
