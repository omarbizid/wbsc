select
    s.batch_id,
    s.scope_key,
    s.status as scope_status,
    s.error as scope_error,
    b.source_id,
    b.started_at as batch_started_at
from {{ source('ops', 'batch_scope') }} s
join {{ ref('stg_batches') }} b using (batch_id)
