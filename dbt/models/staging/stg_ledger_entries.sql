-- Ledger entries with their transaction, account kind and pseudonymised reporter.
select
    e.entry_id,
    e.txn_id,
    t.kind as txn_kind,
    t.case_id,
    t.fine_id,
    t.created_at,
    e.account_id,
    a.kind as account_kind,
    case when a.reporter_id is not null then {{ pseudonym('a.reporter_id', 'reporter') }} end
        as reporter_key,
    e.amount_cents
from {{ source('ledger', 'entries') }} as e
inner join {{ source('ledger', 'transactions') }} as t on e.txn_id = t.txn_id
inner join {{ source('ledger', 'accounts') }} as a on e.account_id = a.account_id
