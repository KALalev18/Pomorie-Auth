-- Only non-identifying columns leave the identity schema.
select
    {{ pseudonym('reporter_id', 'reporter') }} as reporter_key,
    created_at as registered_at,
    erased_at is not null as is_erased
from {{ source('identity', 'reporters') }}
