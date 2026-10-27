select
    dead_letter_id,
    kafka_topic,
    stage,
    split_part(reasons[1], ':', 1) as primary_reason,
    cardinality(reasons) as reason_count,
    created_at
from {{ source('raw', 'dead_letter') }}
