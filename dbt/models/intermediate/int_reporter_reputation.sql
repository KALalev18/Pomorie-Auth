-- Reputation from how authorities judged a reporter's cases. Laplace smoothing
-- ((confirmed + 1) / (decided + 2)) keeps one early rejection from ruining a new reporter.
with per_report as (
    select
        r.reporter_key,
        r.case_id,
        r.is_flagged,
        c.status
    from {{ ref('stg_reports') }} as r
    inner join {{ ref('stg_cases') }} as c on r.case_id = c.case_id
),

totals as (
    select
        reporter_key,
        count(*) as reports,
        count(distinct case_id) as cases,
        count(distinct case_id) filter (where status in ('resolved', 'fined', 'paid')) as confirmed,
        count(distinct case_id) filter (where status = 'rejected') as rejected,
        count(*) filter (where is_flagged) as flagged_reports
    from per_report
    group by reporter_key
),

scored as (
    select
        *,
        round((confirmed + 1)::numeric / (confirmed + rejected + 2), 3) as reputation_score
    from totals
)

select
    *,
    case
        when flagged_reports > 0 then 'watch'
        when confirmed + rejected >= 3 and reputation_score < 0.4 then 'watch'
        when confirmed >= 5 and reputation_score >= 0.8 then 'trusted'
        else 'standard'
    end as reputation_tier
from scored
