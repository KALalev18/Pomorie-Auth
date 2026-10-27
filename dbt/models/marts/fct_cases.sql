with fines as (
    select
        case_id,
        sum(amount_cents) as fine_cents,
        bool_or(is_paid) as fine_paid
    from {{ ref('stg_fines') }}
    group by case_id
)

select
    c.case_id,
    c.category,
    c.authority,
    c.status,
    c.settlement,
    c.street,
    c.lat,
    c.lon,
    c.report_count,
    c.first_reported_at::date as date_key,
    c.first_reported_at,
    c.routed_at,
    c.sla_due_at,
    c.decided_at,
    c.closed_at,
    c.hours_to_decision,
    c.sla_breached,
    c.needs_review,
    c.review_decision,
    c.review_reasons,
    cr.rule_key,
    coalesce(f.fine_cents, 0) as fine_cents,
    coalesce(f.fine_paid, false) as fine_paid
from {{ ref('int_case_lifecycle') }} as c
left join fines as f on c.case_id = f.case_id
left join {{ ref('dim_category_rule') }} as cr
    on
        c.category = cr.category
        and c.first_reported_at >= cr.valid_from
        and c.first_reported_at < cr.valid_to
