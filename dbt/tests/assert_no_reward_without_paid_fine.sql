-- A reward accrual must point at a fine that has been paid.
select l.txn_id
from {{ ref('fct_reward_ledger') }} as l
left join {{ ref('fct_fines') }} as f on l.fine_id = f.fine_id
where l.txn_kind = 'reward_accrual' and (f.fine_id is null or not f.is_paid)
