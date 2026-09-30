-- Processing history (collection log) with the batch outcome.
select
    l.*,
    b.status as batch_status,
    b.started_at as batch_started_at,
    b.is_synthetic
from {{ ref('stg_load_runs') }} l
join {{ source('ops', 'collection_batch') }} b using (batch_id)
