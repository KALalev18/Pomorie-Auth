-- Double entry: the entries of every transaction sum to zero.
select
    txn_id,
    sum(amount_cents) as imbalance
from {{ ref('fct_reward_ledger') }}
group by txn_id
having sum(amount_cents) <> 0
