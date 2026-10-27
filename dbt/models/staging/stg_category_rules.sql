-- Type-2 rule history as stored at the source.
select
    category,
    authority,
    sla_hours,
    dedup_radius_m,
    dedup_window_hours,
    fine_cents,
    reward_share_bp,
    valid_from,
    valid_to,
    valid_to is null as is_current
from {{ source('ref', 'category_rules') }}
