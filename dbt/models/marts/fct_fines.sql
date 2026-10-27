select
    f.fine_id,
    f.case_id,
    c.category,
    f.authority,
    f.amount_cents,
    f.currency,
    f.issued_at,
    f.issued_at::date as date_key,
    f.paid_at,
    f.is_paid,
    extract(epoch from f.paid_at - f.issued_at) / 86400.0 as days_to_payment
from {{ ref('stg_fines') }} as f
inner join {{ ref('stg_cases') }} as c on f.case_id = c.case_id
