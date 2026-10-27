{#
  SCD type 2 history of reporter reputation tiers. Each run compares the current tier with
  the latest snapshot row and, when it changed, closes the old row (dbt_valid_to) and
  opens a new one. Orchestrated daily by Dagster.
#}
{% snapshot reporter_reputation_snapshot %}
{{
    config(
        unique_key='reporter_key',
        strategy='check',
        check_cols=['reputation_tier'],
        invalidate_hard_deletes=True,
    )
}}
select reporter_key, reputation_tier, reputation_score, cases, confirmed, rejected
from {{ ref('int_reporter_reputation') }}
{% endsnapshot %}
