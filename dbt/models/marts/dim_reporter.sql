-- Pseudonymised reporters: no names, e-mails or raw ids. reporter_key is an HMAC.
select
    r.reporter_key,
    r.registered_at,
    r.is_erased,
    coalesce(rep.reports, 0) as reports,
    coalesce(rep.cases, 0) as cases,
    rep.reputation_score,
    coalesce(rep.reputation_tier, 'new') as reputation_tier
from {{ ref('stg_reporters') }} as r
left join {{ ref('int_reporter_reputation') }} as rep on r.reporter_key = rep.reporter_key
