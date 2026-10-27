-- One row per case with its decision time and SLA outcome.
with decisions as (
    select
        case_id,
        min(changed_at) as decided_at
    from {{ ref('stg_case_status_history') }}
    where source = 'authority' and status in ('rejected', 'resolved', 'fined')
    group by case_id
),

first_report as (
    select distinct on (case_id)
        case_id,
        settlement,
        street,
        reporter_key as first_reporter_key
    from {{ ref('stg_reports') }}
    order by case_id, received_at, report_id
)

select
    c.*,
    fr.settlement,
    fr.street,
    fr.first_reporter_key,
    d.decided_at,
    extract(epoch from d.decided_at - c.routed_at) / 3600.0 as hours_to_decision,
    -- Undecided cases count as breached once their deadline has passed.
    coalesce(d.decided_at, current_timestamp) > c.sla_due_at as sla_breached
from {{ ref('stg_cases') }} as c
left join decisions as d on c.case_id = d.case_id
left join first_report as fr on c.case_id = fr.case_id
