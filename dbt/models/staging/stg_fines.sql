select
    fine_id,
    case_id,
    authority,
    amount_cents,
    currency,
    issued_at,
    paid_at,
    paid_at is not null as is_paid
from {{ source('ops', 'fines') }}
