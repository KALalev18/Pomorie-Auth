-- Entry grain. Positive = debit, negative = credit; every txn sums to zero (tested).
select
    entry_id,
    txn_id,
    txn_kind,
    case_id,
    fine_id,
    created_at,
    created_at::date as date_key,
    account_id,
    account_kind,
    reporter_key,
    amount_cents
from {{ ref('stg_ledger_entries') }}
