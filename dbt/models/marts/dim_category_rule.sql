-- SCD type 2: one row per version of a category's routing and reward rule.
select
    category || '@' || to_char(valid_from at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI') as rule_key,
    category,
    authority,
    sla_hours,
    dedup_radius_m,
    dedup_window_hours,
    fine_cents,
    reward_share_bp,
    valid_from,
    coalesce(valid_to, 'infinity'::timestamptz) as valid_to,
    is_current
from {{ ref('stg_category_rules') }}
