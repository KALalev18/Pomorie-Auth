-- Reconciliation: each accrued reward equals floor(fine * share) under the rule version
-- that was valid when the case was first reported.
with accrued as (
    select
        fine_id,
        sum(amount_cents) as reward_cents
    from {{ ref('fct_reward_ledger') }}
    where txn_kind = 'reward_accrual' and account_kind = 'expense'
    group by fine_id
)

select
    a.fine_id,
    a.reward_cents,
    f.amount_cents * r.reward_share_bp / 10000 as expected_cents
from accrued as a
inner join {{ ref('fct_fines') }} as f on a.fine_id = f.fine_id
inner join {{ ref('fct_cases') }} as c on f.case_id = c.case_id
inner join {{ ref('dim_category_rule') }} as r on c.rule_key = r.rule_key
where a.reward_cents <> f.amount_cents * r.reward_share_bp / 10000
