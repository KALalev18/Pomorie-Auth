-- Rejected events per day, stage and reason: the input-quality trend.
select
    created_at::date as date_key,
    kafka_topic,
    stage,
    primary_reason,
    count(*) as events
from {{ ref('stg_dead_letter') }}
group by 1, 2, 3, 4
