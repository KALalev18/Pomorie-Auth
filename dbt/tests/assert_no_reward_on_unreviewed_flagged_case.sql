-- Fraud hold: a flagged case earns nothing until a reviewer approves it.
select l.txn_id
from {{ ref('fct_reward_ledger') }} as l
inner join {{ ref('fct_cases') }} as c on l.case_id = c.case_id
where
    l.txn_kind = 'reward_accrual'
    and c.needs_review
    and c.review_decision is distinct from 'approved'
