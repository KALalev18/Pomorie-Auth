-- Current rule per category; the full history is in dim_category_rule.
select
    category,
    authority,
    sla_hours,
    fine_cents,
    reward_share_bp,
    fine_cents is not null as can_be_fined,
    (
        select count(*) from {{ ref('stg_category_rules') }} as h
        where h.category = r.category)
        as rule_versions
from {{ ref('stg_category_rules') }} as r
where is_current
