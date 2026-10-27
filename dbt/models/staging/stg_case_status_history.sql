select
    case_id,
    status,
    changed_at,
    source
from {{ source('ops', 'case_status_history') }}
