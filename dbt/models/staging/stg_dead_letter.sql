-- Rejected events. Semantic reasons are already short codes ("outside_boundary: ...");
-- parse and contract failures get a readable code instead of a JSON path.
select
    dead_letter_id,
    kafka_topic,
    stage,
    case stage
        when 'parse' then 'invalid_json'
        when 'contract' then 'contract_violation'
        when 'processing' then 'processing_error'
        else split_part(reasons[1], ':', 1)
    end as primary_reason,
    cardinality(reasons) as reason_count,
    created_at
from {{ source('raw', 'dead_letter') }}
